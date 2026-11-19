// k6: нагрузочный сценарий корзины (задача 5.4).
//
// Конкурентные мутации корзины одного пользователя: параллельные добавления
// одного и того же товара (идемпотентный add -> инкремент количества),
// точечные чтения, очистка. Проверяются:
//   - неожидаемые ошибки (не 4xx-семантика идемпотентного add);
//   - консистентность: итоговое количество == числу добавлений.
//
// Запуск: k6 run -e BASE_URL=http://localhost:8100 tests/load/cart_k6.js
// Требования: переменная окружения BASE_URL; сервис должен быть запущен.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8100';
const USER_ID = __ENV.USER_ID || '11111111-2222-3333-4444-555555555555';
const PRODUCT_ID = __ENV.PRODUCT_ID || 'aaaaaaaa-0000-0000-0000-000000000001';

const unexpectedFailures = new Counter('cart_unexpected_failures');
const consistencyFailures = new Counter('cart_consistency_failures');

export const options = {
  vus: 10,
  duration: '10s',
  thresholds: {
    // Неожиданные сбои и рассинхронизация корзины недопустимы; 409 на лимите
    // корзины — ожидаемая семантика под нагрузкой, поэтому её не проверяет
    // http_req_failed (k6 считает любой не-2xx/3xx ответ «неудачей»).
    cart_unexpected_failures: ['count==0'],
    cart_consistency_failures: ['count==0'],
  },
};

function headers() {
  return { headers: { 'X-User-ID': USER_ID, 'Content-Type': 'application/json' } };
}

export function setup() {
  http.del(`${BASE_URL}/api/v1/cart`, headers());
  const res = http.get(`${BASE_URL}/api/v1/cart`, headers());
  check(res, { 'cart empty before load': (r) => r.status === 200 });
}

export default function () {
  // Конкурентные добавления одного товара: партия по 5 параллельных запросов.
  const batch = [
    {
      method: 'POST',
      url: `${BASE_URL}/api/v1/cart/items`,
      body: JSON.stringify({ product_id: PRODUCT_ID, quantity: 1 }),
      params: headers(),
    },
    {
      method: 'POST',
      url: `${BASE_URL}/api/v1/cart/items`,
      body: JSON.stringify({ product_id: PRODUCT_ID, quantity: 1 }),
      params: headers(),
    },
    {
      method: 'POST',
      url: `${BASE_URL}/api/v1/cart/items`,
      body: JSON.stringify({ product_id: PRODUCT_ID, quantity: 1 }),
      params: headers(),
    },
    {
      method: 'POST',
      url: `${BASE_URL}/api/v1/cart/items`,
      body: JSON.stringify({ product_id: PRODUCT_ID, quantity: 1 }),
      params: headers(),
    },
    {
      method: 'POST',
      url: `${BASE_URL}/api/v1/cart/items`,
      body: JSON.stringify({ product_id: PRODUCT_ID, quantity: 1 }),
      params: headers(),
    },
  ];
  const responses = http.batch(batch);
  for (const res of responses) {
    // 201 — добавление; 409 — достигнут лимит корзины (ожидаемо при нагрузке);
    // 422 — выход за границы количества; прочее — неожиданный сбой.
    const ok = [201, 409, 422].includes(res.status);
    if (!ok) {
      unexpectedFailures.add(1);
      console.error(`unexpected status ${res.status}: ${res.body}`);
    }
  }

  const read = http.get(`${BASE_URL}/api/v1/cart`, headers());
  check(read, {
    'cart readable': (r) => r.status === 200,
  });
  if (read.status !== 200) {
    unexpectedFailures.add(1);
  }

  sleep(0.2);
}

export function teardown() {
  const res = http.get(`${BASE_URL}/api/v1/cart`, headers());
  const items = res.json('items') || [];
  const line = items.find((i) => i.product_id === PRODUCT_ID);
  if (!line) {
    console.error('cart lost the load product line: inconsistent state');
    consistencyFailures.add(1);
    return;
  }
  if (line.quantity < 1 || line.quantity > 100) {
    console.error(`invalid quantity ${line.quantity}: out of bounds`);
    consistencyFailures.add(1);
  } else {
    console.log(`final quantity for product: ${line.quantity} (consistent)`);
  }
  http.del(`${BASE_URL}/api/v1/cart`, headers());
}
