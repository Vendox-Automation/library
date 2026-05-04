import pytest
from unittest.mock import MagicMock, patch
from src.vdx_auto_utils.database import Database

class TestDatabase:

    def test_raises_value_error_for_unsupported_type(self):
        db = Database("mysql")
        with pytest.raises(ValueError, match="Invalid database type"):
            db.connect()

    def test_connect_supabase_success(self):
        db = Database("supabase", user="u", password="p", host="h", port="5432", dbname="db")
        mock_conn = MagicMock()

        with patch("psycopg2.connect", return_value=mock_conn):
            result = db.connect()

        assert result == mock_conn
        assert db.connection == mock_conn

    def test_connect_supabase_failure_raises(self):
        db = Database("supabase", user="u", password="wrong")

        with patch("psycopg2.connect", side_effect=Exception("auth failed")):
            with pytest.raises(Exception, match="auth failed"):
                db.connect()

    def test_write_row_success(self):
        db = Database("supabase")
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        db.connection = mock_conn

        result = db.write_row("INSERT INTO t VALUES (%s)", ("val",))

        assert result is True
        mock_cursor.execute.assert_called_once_with("INSERT INTO t VALUES (%s)", ("val",))
        mock_conn.commit.assert_called_once()

    def test_write_row_failure_returns_false(self):
        db = Database("supabase")
        mock_conn = MagicMock()
        mock_conn.cursor.side_effect = Exception("db error")
        db.connection = mock_conn

        result = db.write_row("INSERT INTO t VALUES (%s)", ("val",))

        assert result is False
        mock_conn.rollback.assert_called_once()

    def test_write_row_raises_when_not_connected(self):
        db = Database("supabase")
        with pytest.raises(ConnectionError):
            db.write_row("INSERT INTO t VALUES (%s)", ("val",))

    def test_read_table_returns_dataframe(self):
        import pandas as pd
        db = Database("supabase")
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [(1, "Alice"), (2, "Bob")]
        mock_cursor.description = [("id",), ("name",)]
        mock_conn.cursor.return_value = mock_cursor
        db.connection = mock_conn

        result = db.read_table("SELECT * FROM users")

        assert isinstance(result, pd.DataFrame)
        assert list(result.columns) == ["id", "name"]
        assert len(result) == 2

    def test_update_row_success(self):
        db = Database("supabase")
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        db.connection = mock_conn

        result = db.update_row("UPDATE t SET col=%s WHERE id=%s", ("val", 1))

        assert result is True
        mock_conn.commit.assert_called_once()

    def test_close_clears_connection(self):
        db = Database("supabase")
        mock_conn = MagicMock()
        db.connection = mock_conn

        db.close()

        mock_conn.close.assert_called_once()
        assert db.connection is None

    def test_context_manager(self):
        mock_conn = MagicMock()

        with patch("psycopg2.connect", return_value=mock_conn):
            with Database("supabase", user="u", password="p", host="h", port="5432", dbname="db") as db:
                assert db.connection == mock_conn

        mock_conn.close.assert_called_once()