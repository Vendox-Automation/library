## Contributing

To contribute to this library, please follow these steps to maintain consistency and ensure your new features are accessible:

### 1. Create a New Module
* Create a new `.py` file for your logic (e.g., `new_feature.py`).
* Encapsulate your logic within a **class**.
* Define a clear `__init__` function to handle setup/credentials.
* Write **inner functions** (methods) using descriptive names and consistent error handling (use the `logger`).

### 2. Export via `__init__.py`
* Open `src/vdx_auto_utils/__init__.py`.
* Import your new class: `from .new_feature import NewFeature`.
* Add the class name to the `__all__` list so it can be imported directly from the package.

### 3. Update Configuration
* **Dependencies**: If your code requires new external libraries (like `selenium` or `requests`), add them to the `dependencies` list in `pyproject.toml`.
* **Version Number**: Increment the `version` string in `pyproject.toml` (e.g., from `0.1.0` to `0.1.1`) to reflect the update.

### 4. Style & Documentation
* Follow the existing style, such as using `WebDriverWait` for Selenium or `try-except` blocks with `traceback`.
* Include docstrings for your class and all public methods, detailing the **Args** and the purpose of the code.

Please ensure your code follows the existing style and includes appropriate documentation.