"""
Only support Supabase database.
"""

import psycopg2
import pandas as pd

class Database:
    """
    A database connection manager for PostgreSQL-based databases.

    Supports connection management, table operations, and data manipulation
    with context manager support for automatic resource cleanup.
    """

    def __init__(self, database_type: str, user: str = None, password: str = None,
                 host: str = None, port: str = None, dbname: str = None):
        """
        Initialize a Database instance.

        Args:
            database_type (str): Type of database to connect to (currently supports "supabase")
            user (str, optional): Database user name
            password (str, optional): Database password
            host (str, optional): Database host address
            port (str, optional): Database port number
            dbname (str, optional): Database name

        Usage:
            from src.vdx_auto_utils import database
            USER="(your username)"
            PASSWORD="<your password>"
            HOST="<your host>"
            PORT="<your port>"
            DBNAME="<your database name>"

            db = database.Database("supabase", USER, PASSWORD, HOST, PORT, DBNAME)
            db.connect()
            db.create_table("CREATE TABLE test (id SERIAL PRIMARY KEY, name VARCHAR(255))")
            db.write_row("INSERT INTO test (name) VALUES (%s)", ("John Doe",))
            df = db.read_table("SELECT * FROM test")
            print(df)
            db.close()
        """
        self.database_type = database_type
        self.connection = None
        self.cursor = None
        self.user = user
        self.password = password
        self.host = host
        self.port = port
        self.dbname = dbname

    def connect(self):
        """
        Establish a connection to the database.

        Returns:
            psycopg2.connection: Active database connection object

        Raises:
            ValueError: If database_type is not supported
            Exception: If connection fails
        """
        if self.database_type == "supabase":
            try:
                self.connection = psycopg2.connect(
                    user=self.user,
                    password=self.password,
                    host=self.host,
                    port=self.port,
                    dbname=self.dbname
                )
                print("Connection successful!")
                return self.connection
            except Exception as e:
                print(f"Failed to connect: {e}")
                raise
        else:
            raise ValueError(f"Invalid database type: {self.database_type}")

    def create_table(self, query: str):
        """
        Create a table in the database using the provided SQL query.

        Args:
            query (str): SQL CREATE TABLE query

        Raises:
            ConnectionError: If database is not connected
            ValueError: If database_type is not supported
            Exception: If table creation fails (suppressed if table already exists)
        """
        if self.database_type == "supabase":
            if not self.connection:
                raise ConnectionError("Database not connected. Call connect() first.")
            try:
                cursor = self.connection.cursor()
                cursor.execute(query)
                self.connection.commit()
                cursor.close()
                print("Table created")
            except Exception as e:
                msg = str(e)
                if "already exists" in msg or "DuplicateTable" in msg:
                    print("Table already exists")
                else:
                    print(f"Error creating table: {e}")
                    raise
        else:
            raise ValueError(f"Invalid database type: {self.database_type}")

    def write_row(self, insert_query: str, values: tuple):
        """
        Insert a row into a table using parameterized query.

        Args:
            insert_query (str): SQL INSERT query with placeholders (e.g., "INSERT INTO table VALUES (%s, %s)")
            values (tuple): Tuple of values to insert

        Returns:
            bool: True if insertion successful, False otherwise

        Raises:
            ConnectionError: If database is not connected
            ValueError: If database_type is not supported
        """
        if self.database_type == "supabase":
            if not self.connection:
                raise ConnectionError("Database not connected. Call connect() first.")
            try:
                cursor = self.connection.cursor()
                cursor.execute(insert_query, values)
                self.connection.commit()
                cursor.close()
                print("Row inserted successfully!")
                return True
            except Exception as e:
                msg = str(e)
                print(f"Error inserting row: {msg}")
                if self.connection:
                    self.connection.rollback()
                return False
        else:
            raise ValueError(f"Invalid database type: {self.database_type}")

    def update_row(self, update_query: str, values: tuple):
        """
        Update row(s) using a parameterized query.

        Args:
            update_query (str): SQL UPDATE query with placeholders (e.g., "UPDATE t SET col=%s WHERE id=%s")
            values (tuple): Tuple of values for the placeholders

        Returns:
            bool: True if update succeeded, False otherwise

        Raises:
            ConnectionError: If database is not connected
            ValueError: If database_type is not supported
        """
        if self.database_type == "supabase":
            if not self.connection:
                raise ConnectionError("Database not connected. Call connect() first.")
            try:
                cursor = self.connection.cursor()
                cursor.execute(update_query, values)
                self.connection.commit()
                cursor.close()
                print("Row updated successfully!")
                return True
            except Exception as e:
                msg = str(e)
                print(f"Error updating row: {msg}")
                if self.connection:
                    self.connection.rollback()
                return False
        else:
            raise ValueError(f"Invalid database type: {self.database_type}")

    def read_table(self, query: str):
        """
        Execute a SELECT query and return results as a pandas DataFrame.

        Args:
            query (str): SQL SELECT query

        Returns:
            pd.DataFrame: Query results as DataFrame, or None if query fails

        Raises:
            ConnectionError: If database is not connected
            ValueError: If database_type is not supported
        """
        if self.database_type == "supabase":
            if not self.connection:
                raise ConnectionError("Database not connected. Call connect() first.")
            try:
                cursor = self.connection.cursor()
                cursor.execute(query)
                results = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                cursor.close()
                df = pd.DataFrame(results, columns=columns)
                return df
            except Exception as e:
                msg = str(e)
                print(f"Error reading table: {msg}")
                return None
        else:
            raise ValueError(f"Invalid database type: {self.database_type}")

    def close(self):
        """
        Close the database connection and cleanup resources.
        """
        if self.connection:
            self.connection.close()
            print("Connection closed")
            self.connection = None

    def __enter__(self):
        """
        Context manager entry point. Establishes database connection.

        Returns:
            Database: Self instance with active connection
        """
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Context manager exit point. Closes database connection.

        Args:
            exc_type: Exception type if an exception occurred
            exc_val: Exception value if an exception occurred
            exc_tb: Exception traceback if an exception occurred
        """
        self.close()
