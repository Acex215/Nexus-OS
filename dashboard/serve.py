"""
NEXUS Dashboard Server — ThinkStation deployment
Serves static React build + API proxy to Pi cluster services
"""
import os
import sys

# Add api directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'api'))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

# Import the dashboard API app
from dashboard_api import app as api_app

# Create main app
app = FastAPI(title="NEXUS Dashboard")

# Mount the API routes
app.mount("/api", api_app)

# Serve static files from dist/
dist_dir = os.path.join(os.path.dirname(__file__), 'dist')
app.mount("/assets", StaticFiles(directory=os.path.join(dist_dir, 'assets')), name='assets')

# Serve static public files (favicon, manifest, logo)
@app.get("/favicon.ico")
async def favicon():
    return FileResponse(os.path.join(dist_dir, 'favicon.ico'))

@app.get("/manifest.json")
async def manifest():
    return FileResponse(os.path.join(dist_dir, 'manifest.json'))

@app.get("/nexus-logo.png")
async def logo():
    return FileResponse(os.path.join(dist_dir, 'nexus-logo.png'))

@app.get("/nexus-192.png")
async def icon192():
    return FileResponse(os.path.join(dist_dir, 'nexus-192.png'))

@app.get("/nexus-512.png")
async def icon512():
    return FileResponse(os.path.join(dist_dir, 'nexus-512.png'))

@app.get("/apple-touch-icon.png")
async def apple_icon():
    return FileResponse(os.path.join(dist_dir, 'apple-touch-icon.png'))

# SPA fallback — serve index.html for all other routes
@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    file_path = os.path.join(dist_dir, full_path)
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    return FileResponse(os.path.join(dist_dir, 'index.html'))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3000, log_level="info")
