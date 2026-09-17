import pytest
from testcontainers.postgres import PostgresContainer
from testcontainers.kafka import KafkaContainer

def test_postgres_container():
    with PostgresContainer("postgres:16-alpine") as postgres:
        url = postgres.get_connection_url()
        assert "postgresql+psycopg2://" in url or "postgresql://" in url

def test_kafka_container():
    with KafkaContainer("confluentinc/cp-kafka:7.6.0") as kafka:
        bootstrap_server = kafka.get_bootstrap_server()
        assert bootstrap_server is not None
