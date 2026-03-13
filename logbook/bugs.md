# Bugs & Issues Tracking Log

This document contains all the bugs across different projects we came across so far.

**Author:**
> Potter | potter@4896.co

---

## Table of Contents
1. [Bug Category](#bug-category)
2. [Active Bug Log](#active-bug-log)
3. [Resolution History](#resolution-history)
4. [Reporting Template](#reporting-template)

---

## Bug Category

### 🔴 High Impact (Critical/Blocker)
Bugs that cause system crashes, memory leaks, data corruption, or prevent the user from completing core workflows. These require immediate hotfixes.

### 🟡 Medium Impact (Functional)
Bugs where a feature is not working as intended, but the rest of the application remains stable or a temporary workaround exists.

### 🟢 Low Impact Bugs
Low impact bugs usually occur from error syntax and input variables. These include UI misalignments, typos, or minor validation errors that do not break the application flow.

---

## Bug Logs

### [ID-001] PID lurker
- **Project:** [Payment Gateway Checker]

- **Category:** [High]

- **Status:** Closed

- **Description:** When calling ```driver.quit()``` in the code block, it might not work as intended when the driver dies midway before it reaches the quit call. This results in the browser still lurking in the background because ```driver.quit()``` can no longer find the driver that was involved in opening the browser in the first place. This leads to the **dead** browser hanging in the background and hogging resources.

- **Fixes:** Keeping a record of the first child pid,
```python
child_pid = ""
    try:
        driver = popupcloser.setup_driver()
        if not driver:
            LOGGER_STATUS = "driverFAIL"
            LOGGER_REASON = "Failed to setup driver"
            raise Exception(LOGGER_REASON)
        driver.get(TARGET_URL)
        time.sleep(1) # Consider changing this to a WebDriverWait
        
        # 1. Get the Main Driver PID (The Parent)
        parent_pid = driver.service.process.pid
        # 2. Create a psutil Process object for the parent
        parent = psutil.Process(parent_pid)
        # 3. Find all children (recursive=True gets grandchildren too)
        children = parent.children(recursive=True)
        child_pid = children[0] if children else None
```
Then try to delete it if driver.quit() doesn't work as intended
```python
finally:
        if driver:
            print(f"Driver PID (process id): {driver.service.process.pid}")
            try:
                driver.quit()
            except: pass
            
        if child_pid:
            try:
                child_pid.kill()
            except: pass
```
We are assuming the first children pid is the broswer in this case (Most of the time).

---
### [ID-002] Above 9000
- **Project:** [Library]
- **Category:** [Medium]
- **Status:** Closed
- **Description:** When uploading more than the row limit in google sheets, upload operation/function will stop working.
- **Fixes:** Before uploading, we have to check compare row limit to upload size then resize appropriately

---
### [ID-003] Houdini in the sheets

- **Project:** [Library]
- **Category:** [High]
- **Status:** Closed
- **Description:** When uploading the big chunk of data to google sheets **at once**, it might resize the amount of columns and remove some nessesary columns at later stages.
- **Fixes:** Make sure columns are never resized in the first place. Resizing columns means corrupting data pasted

---

### [ID-004] Invinsible buttons
- **Project:** [Payment-Gateway-Checker/Hogan-Onetime-Project]
- **Category:** [Medium]
- **Status:** Closed
- **Description:** Calling a function to click a button might not work as intended if there is no buffer between processes, for instance, button 2 might not be clicked if it's not loaded the moment it's called which brings us to a missed timing. 
```python
click_button_1(driver)
# No buffer
click_button_2(driver)
```
- **Fixes:** Simply add a buffer or a retry mechanism in between clicks, trade off might be the result of slower execution time.
```python
click_button_1(driver)
time.sleep(0.2) #Adjust to own liking
click_button_2(driver)
```
---

### [ID-005] Misaligned dataframes
- **Project:** [WD-Project-1]
- **Category:** [Medium]
- **Status:** Closed
- **Description:** Some csvs will have columns in between dataframes without any headers. When converted into a dataframe without any prior intervention, the column headers will be misaligned where the last column in the csv will be missing from the dataframe.
- **Fixes:** Force headers onto dataframe before converting the csv to a dataframe. This prevents misaligned column headers after conversion.
```python
if 'force_headers' in config:
                    print(f"   🔧 Applying forced headers for {project_key}...")
                    if len(raw_df.columns) < len(config['force_headers']):
                        print("      -> shift detected (Index contains data). Resetting index...")
                        raw_df.reset_index(inplace=True)
                    
                    if len(raw_df.columns) == len(config['force_headers']):
                        raw_df.columns = config['force_headers']
                        print("      ✅ Headers aligned successfully.")
                    else:
                        print(f"      ⚠️ Header Mismatch: Data has {len(raw_df.columns)} cols, Config expects {len(config['force_headers'])}")
```

### [ID-006] Nan/None/NA values in pandas dataframes
- **Project:** [Hogan-Onetime-Project]
- **Category:** [Low]
- **Status:** Closed
- **Description:** When converting csv/excel or other datafiles to pandas dataframe, pandas might convert "None" or "NA" to blank cells which might be an issue depending on the task on hand. For instance, when filling in a form that doesn't accept an empty value, the form might not be filled properly and overlooked at times.
- **Fixes:** Either clean up the data before processing or have a validation part before parsing in input from csv.

---
## Reporting Template
*To be used when adding new entries to this log:*

### [ID-XXX] Bug Name
- **Project:** [Project Name]
- **Category:** [High/Medium/Low]
- **Status:** Open
- **Description:** Summary of the issue.
- **Fixes:** Fixes
- **Syntax/Input Involved:** (e.g., Variable `x` expected String, received Null)