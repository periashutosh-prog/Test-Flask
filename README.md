# TV Remote Control - Vercel + Local Deployment

A Flask-based remote control for Android TVs using `androidtvremote2`. Runs on both Vercel (serverless) and locally.

## Local Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run Locally
```bash
python main.py
```
Open `http://localhost:5000` in your browser.

## Vercel Deployment

### 1. Prerequisites
- GitHub account with your repo
- Vercel account (free at https://vercel.com)

### 2. Deploy Steps

**Option A: Using Vercel CLI**
```bash
# Install Vercel CLI
npm install -g vercel

# Deploy from project directory
vercel
```

**Option B: Using GitHub Integration**
1. Push your code to GitHub
2. Go to https://vercel.com/new
3. Select your repository
4. Vercel auto-detects `vercel.json` and deploys

### 3. Environment Variables (Vercel Dashboard)
If you need to add secrets:
1. Go to your Vercel project settings
2. Add environment variables in "Environment Variables" section
3. Redeploy after adding vars

## How It Works

### Local Execution
- `main.py` is the entry point
- Runs Flask development server on `0.0.0.0:5000`
- Keeps existing asyncio event loop for Android TV connections

### Vercel Execution
- `api/index.py` imports `app` from `main.py`
- Vercel serves it as a serverless function
- Flask handles all HTTP requests
- Each request gets its own Lambda execution context

## Key Files

- **`main.py`** - Flask app & business logic
- **`api/index.py`** - Vercel entry point (imports Flask app)
- **`vercel.json`** - Vercel build & routing config
- **`requirements.txt`** - Python dependencies

## Notes

- Certificates (`cert_*.pem`, `key_*.pem`) and `config.json` are Git-ignored for security
- Each pairing is device-specific and must be done per deployment
- On Vercel, certificates persist in the deployment but device discovery only works on your local network
