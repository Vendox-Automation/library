# Database Documentation

## Table of Contents
- [How to Use in Your Project](#how-to-use-in-your-project)
  - [Quick Start Guide](#quick-start-guide)
- [Overview](#overview)
- [Class: Database](#class-database)
  - [Initialization](#initialization)
  - [Methods](#methods)
    - [connect](#connect)
    - [create_table](#create_table)
    - [write_row](#write_row)
    - [read_table](#read_table)
    - [close](#close)
  - [Context Manager Support](#context-manager-support)
- [Usage Example](#usage-example)

## How to Use in Your Project

The `Database` class is a connection manager for PostgreSQL-based databases (currently Supabase). It handles connecting, creating tables, inserting rows, and reading data — all returning clean results or raising clear errors.

### Quick Start Guide

1. **Import the Class**:
    ```python
    from functions.database import Database
    ```

2. **Initialize**:
    Pass in your credentials and database type.
    ```python
    db = Database(
        database_type="supabase",
        user="your_user",
        password="your_password",
        host="your_host",
        port="5432",
        dbname="your_dbname"
    )
    ```

3. **Connect**:
    ```python
    db.connect()
    ```

4. **Do Your Work**:
    ```python
    db.create_table("CREATE TABLE orders (id SERIAL PRIMARY KEY, name VARCHAR(255))")
    db.write_row("INSERT INTO orders (name) VALUES (%s)", ("Order A",))
    df = db.read_table("SELECT * FROM orders")
    ```

5. **Close the Connection**:
    ```python
    db.close()
    ```

6. **OR use as a Context Manager** (recommended — auto-closes on exit):
    ```python
    with Database("supabase", user, password, host, port, dbname) as db:
        df = db.read_table("SELECT * FROM orders")
    ```

---

## Overview

The `Database` class provides a straightforward interface for interacting with a Supabase (PostgreSQL) database. It wraps `psycopg2` for connection management and returns query results as Pandas DataFrames. It also supports Python's context manager protocol (`with` statement) for automatic resource cleanup.

---

## Class: `Database`

### Initialization
```python
def __init__(self, database_type: str, user: str = None, password: str = None,
             host: str = None, port: str = None, dbname: str = None)
```
Sets up the instance with connection credentials. Does **not** connect automatically — call `connect()` first.

- **Parameters:**
  - `database_type` (str): Type of database. Currently only `"supabase"` is supported.
  - `user` (str): Database username.
  - `password` (str): Database password.
  - `host` (str): Host address of the database server.
  - `port` (str): Port number (e.g. `"5432"`).
  - `dbname` (str): Name of the database.

---

### Methods

#### `connect`
```python
def connect(self) -> psycopg2.connection
```
Establishes a connection to the database and stores it internally.

- **Returns:** Active `psycopg2` connection object.
- **Raises:**
  - `ValueError`: If `database_type` is not supported.
  - `Exception`: If the connection attempt fails (e.g. wrong credentials, unreachable host).

---

#### `create_table`
```python
def create_table(self, query: str)
```
Executes a `CREATE TABLE` SQL statement. Silently handles the case where the table already exists.

- **Parameters:**
  - `query` (str): A valid SQL `CREATE TABLE` statement.
- **Raises:**
  - `ConnectionError`: If `connect()` has not been called.
  - `ValueError`: If `database_type` is not supported.
  - `Exception`: For any SQL error other than a duplicate table.

---

#### `write_row`
```python
def write_row(self, insert_query: str, values: tuple) -> bool
```
Inserts a single row using a parameterized query. Rolls back the transaction automatically on failure.

- **Parameters:**
  - `insert_query` (str): SQL `INSERT` statement using `%s` placeholders (e.g. `"INSERT INTO table (col) VALUES (%s)"`).
  - `values` (tuple): Values to bind to the placeholders.
- **Returns:** `True` on success, `False` on failure.
- **Raises:**
  - `ConnectionError`: If `connect()` has not been called.
  - `ValueError`: If `database_type` is not supported.

---

#### `read_table`
```python
def read_table(self, query: str) -> pd.DataFrame
```
Executes a `SELECT` query and returns the results as a Pandas DataFrame.

- **Parameters:**
  - `query` (str): A valid SQL `SELECT` statement.
- **Returns:** `pd.DataFrame` with query results, or `None` if the query fails.
- **Raises:**
  - `ConnectionError`: If `connect()` has not been called.
  - `ValueError`: If `database_type` is not supported.

---

#### `close`
```python
def close(self)
```
Closes the active database connection and resets the internal connection to `None`. Safe to call even if already disconnected.

---

### Context Manager Support

`Database` implements `__enter__` and `__exit__`, so it can be used with Python's `with` statement. The connection is opened automatically on entry and closed on exit — even if an exception is raised.

```python
with Database("supabase", user, password, host, port, dbname) as db:
    df = db.read_table("SELECT * FROM my_table")
    print(df)
# Connection is automatically closed here
```

---

## Usage Example

```python
from functions.database import Database

USER = "your_user"
PASSWORD = "your_password"
HOST = "your_host"
PORT = "5432"
DBNAME = "your_db"

# Standard usage
db = Database("supabase", USER, PASSWORD, HOST, PORT, DBNAME)
db.connect()

db.create_table("""
    CREATE TABLE employees (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255),
        department VARCHAR(100)
    )
""")

db.write_row(
    "INSERT INTO employees (name, department) VALUES (%s, %s)",
    ("Alice", "Engineering")
)

df = db.read_table("SELECT * FROM employees")
print(df)

db.close()

# Context manager usage (recommended)
with Database("supabase", USER, PASSWORD, HOST, PORT, DBNAME) as db:
    df = db.read_table("SELECT * FROM employees WHERE department = 'Engineering'")
    print(df)
```