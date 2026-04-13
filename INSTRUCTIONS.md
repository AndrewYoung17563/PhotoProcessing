# How to Use the Photo OCR Batch Processor
### Plain-English Step-by-Step Guide

---

## What This Program Does

You feed it a folder of scanned photos (front and back of each photo scanned
separately). It reads the back of each photo using AI, pulls out any dates and
notes written there, and saves that information inside the photo file so it
shows up automatically in Apple Photos, Google Photos, Windows Photos, Lightroom,
etc.

---

## Before You Start — One-Time Setup

### Step 1 — Install Python

Python is the language this program is written in. You need it installed first.

**On a Mac:**
1. Open **Terminal** (press Command+Space, type "Terminal", press Enter)
2. Type this and press Enter:
   ```
   python3 --version
   ```
3. If you see something like `Python 3.11.x` you already have it — skip to Step 2.
4. If not, go to **https://www.python.org/downloads/** and click the big
   "Download Python" button. Run the installer and follow the prompts.

**On Windows:**
1. Open **Command Prompt** (press the Windows key, type "cmd", press Enter)
2. Type this and press Enter:
   ```
   python --version
   ```
3. If you see `Python 3.x.x` you already have it — skip to Step 2.
4. If not, go to **https://www.python.org/downloads/** and click the big
   "Download Python" button.
   - **Important:** During installation, tick the box that says
     **"Add Python to PATH"** before clicking Install.

**On Linux:**
1. Open a Terminal
2. Type:
   ```
   python3 --version
   ```
3. If not installed:
   ```
   sudo apt install python3 python3-pip
   ```

---

### Step 2 — Download the Program Files

**Option A — If you have Git installed:**
Open Terminal / Command Prompt and run:
```
git clone <your-repo-url> PhotoProcessing
cd PhotoProcessing
```

**Option B — Download as a ZIP:**
1. Go to the repository page in your browser
2. Click the green **Code** button → **Download ZIP**
3. Unzip it somewhere easy to find, like your Desktop
4. Open Terminal / Command Prompt and navigate to that folder:
   - **Mac/Linux:** `cd ~/Desktop/PhotoProcessing`
   - **Windows:** `cd C:\Users\YourName\Desktop\PhotoProcessing`

---

### Step 3 — Install the Required Libraries

In Terminal / Command Prompt, make sure you are inside the PhotoProcessing
folder (from Step 2), then type:

**Mac/Linux:**
```
pip3 install -r requirements.txt
```

**Windows:**
```
pip install -r requirements.txt
```

You will see a lot of text scroll by — that is normal. Wait for it to finish.

---

### Step 4 — Get an Anthropic API Key

The program uses Claude AI to read the backs of your photos. You need a free
account and an API key to use it.

1. Go to **https://console.anthropic.com** in your browser
2. Click **Sign Up** and create a free account
3. Once logged in, click **API Keys** in the left menu
4. Click **Create Key**, give it a name like "PhotoProcessor", and click Create
5. **Copy the key** — it looks like `sk-ant-api03-...`
   (You only get to see it once, so copy it now!)

Now save it so the program can use it:

**Mac/Linux** — type this in Terminal (replace the part in quotes with your key):
```
export ANTHROPIC_API_KEY="sk-ant-api03-your-key-here"
```

**Windows** — type this in Command Prompt:
```
set ANTHROPIC_API_KEY=sk-ant-api03-your-key-here
```

> **Note:** You will need to do this step every time you open a new Terminal /
> Command Prompt window. See the "Tips" section at the bottom for how to make
> it permanent.

---

## Using the Program

### Step 5 — Prepare Your Photos

Put all your scanned photos into a single folder. They must be in the right
order: **front first, back second, front third, back fourth**, and so on.

Most scanners that scan both sides will name files automatically in this order.
If yours does not, rename them so they sort correctly. Any of these naming
styles work fine:

```
001.jpg   ← front of photo 1
002.jpg   ← back of photo 1
003.jpg   ← front of photo 2
004.jpg   ← back of photo 2
005.jpg   ← front of photo 3
006.jpg   ← back of photo 3
```

Supported file types: **JPG, JPEG, PNG, TIF, TIFF**

---

### Step 6 — Run the Program

Open Terminal / Command Prompt and navigate to the PhotoProcessing folder.

**Recommended — keeps your originals safe, puts results in a new folder:**

*Mac/Linux:*
```
python3 process_photos.py /path/to/your/scans --output-dir /path/to/output
```

*Windows:*
```
python process_photos.py C:\path\to\your\scans --output-dir C:\path\to\output
```

**Example on Mac** (scans are in a folder called "OldPhotos" on the Desktop,
results go to "ProcessedPhotos" on the Desktop):
```
python3 process_photos.py ~/Desktop/OldPhotos --output-dir ~/Desktop/ProcessedPhotos
```

**Example on Windows:**
```
python process_photos.py C:\Users\Jane\Desktop\OldPhotos --output-dir C:\Users\Jane\Desktop\ProcessedPhotos
```

The program will show you what it is doing as it works:
```
Found 10 photo pair(s) to process.

[1/10]  Front: 001.jpg
        Back:  002.jpg
        Running OCR via Claude vision…
        Text:  'Christmas 1967. Grandma and Grandpa in front of the tree.'
        Date:  1967
        Notes: Grandma and Grandpa in front of the tree.
        EXIF metadata written to 001.jpg
        XMP sidecar written: 001.jpg.xmp
...
Done.  10 pair(s) processed.
```

---

### Step 7 — View the Results

Open the output folder. You will find:

| File | What it is |
|------|-----------|
| `001.jpg` | Your front photo, now with date and notes embedded inside it |
| `001.jpg.xmp` | A small extra file that tells photo apps about the date and notes |
| `002.ocr.json` | A text file showing exactly what the AI read from the back |
| `processing_report.json` | A summary of everything that was processed |

Import the photos into **Apple Photos**, **Google Photos**, **Windows Photos**,
or **Lightroom** — the dates and descriptions will appear automatically.

---

## Troubleshooting

**"python3: command not found" / "python is not recognized"**
→ Python is not installed or not on your PATH. Re-do Step 1.

**"No module named anthropic"**
→ The libraries are not installed. Re-do Step 3.

**"Anthropic API key not found"**
→ You need to set your API key again (it resets when you close the terminal).
Re-do Step 4.

**"No supported image files found"**
→ Check that your photos are JPG, PNG, or TIFF and are in the folder you typed.

**The date in the photo is wrong**
→ Open the `.ocr.json` file next to the back scan in any text editor to see
exactly what the AI read. If the handwriting was unclear, the date may have
been misread. You can correct dates manually in your photo app afterwards.

---

## Tips

### Make the API key permanent (so you don't have to re-enter it every time)

**Mac/Linux:**
1. Open Terminal and type:
   ```
   echo 'export ANTHROPIC_API_KEY="sk-ant-api03-your-key-here"' >> ~/.zshrc
   ```
   (Use `~/.bashrc` instead if you use bash)
2. Close and reopen Terminal

**Windows:**
1. Press Windows key, search for "Environment Variables"
2. Click "Edit the system environment variables"
3. Click "Environment Variables…"
4. Under "User variables", click New
5. Variable name: `ANTHROPIC_API_KEY`
6. Variable value: `sk-ant-api03-your-key-here`
7. Click OK

### How much does it cost?
Each back-of-photo scan uses one Claude AI call. A batch of 100 photos costs
roughly $0.20–$1.00 depending on image sizes. You can monitor usage at
https://console.anthropic.com.

### Can I re-run it?
Yes — just run the program again on the same folder. Use `--output-dir` to
avoid overwriting your previous results.
