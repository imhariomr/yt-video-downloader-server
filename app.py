from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os
import re
from pathlib import Path
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

app = Flask(__name__)
CORS(app)

try:
    BASE_DIR = Path(__file__).resolve().parent
    DOWNLOAD_DIR = BASE_DIR / "downloads"
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    logging.info(f"Download directory created at: {DOWNLOAD_DIR}")
except Exception as e:
    logging.error(f"Failed to create download directory: {str(e)}", exc_info=True)

def extract_video_id(url):
    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/)([^&\n?#]+)',
        r'youtube\.com\/embed\/([^&\n?#]+)',
        r'youtube\.com\/v\/([^&\n?#]+)'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def format_duration(seconds):
    if not seconds:
        return '0:00'
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"

def format_bytes(size):
    if not size:
        return "Unknown"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"

@app.route('/api/video-info', methods=['POST'])
def get_video_info():
    try:
        data = request.get_json()
        url = data.get('url') if data else None

        if not url:
            return jsonify({'error': 'URL is required'}), 400

        video_id = extract_video_id(url)
        if not video_id:
            return jsonify({'error': 'Invalid URL'}), 400

        logging.info(f"Fetching info for video: {video_id}")

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'force_ipv4': True,
            'geo_bypass': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        return jsonify({
            'id': video_id,
            'title': info.get('title'),
            'thumbnail': info.get('thumbnail'),
            'duration': format_duration(info.get('duration', 0)),
            'uploader': info.get('uploader'),
            'view_count': info.get('view_count'),
        })

    except Exception as e:
        logging.error(f"Video info error: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/download', methods=['POST'])
def download_video():
    try:
        data = request.get_json()
        url = data.get('url')
        format_id = data.get('format_id')
        quality = data.get('quality', '')

        if not url:
            return jsonify({'error': 'URL is required'}), 400

        video_id = extract_video_id(url)
        if not video_id:
            return jsonify({'error': 'Invalid YouTube URL'}), 400

        logging.info(f"Download started for video: {video_id}")

        ydl_opts = {
            'outtmpl': str(DOWNLOAD_DIR / f'{video_id}_%(title)s.%(ext)s'),
            'retries': 10,
            'fragment_retries': 10,
            'force_ipv4': True,
            'geo_bypass': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
                'Accept-Language': 'en-US,en;q=0.9',
            },
            'quiet': False,
            'no_warnings': False,
        }

        if 'audio' in quality.lower() or format_id == 'bestaudio':
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]
            })
        else:
            ydl_opts.update({
                'format': format_id if format_id else 'bestvideo+bestaudio/best',
                'merge_output_format': 'mp4'
            })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        logging.info("Download finished")

        possible_files = list(DOWNLOAD_DIR.glob(f'{video_id}_*'))
        if not possible_files:
            logging.error("File not found after download")
            return jsonify({'error': 'Download completed but file not found'}), 500

        downloaded_file = max(possible_files, key=os.path.getctime)

        logging.info(f"File ready: {downloaded_file}")

        return jsonify({
            'success': True,
            'filename': downloaded_file.name,
            'download_id': video_id
        })

    except Exception as e:
        logging.error(f"Download error: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/download-file/<filename>', methods=['GET'])
def download_file(filename):
    try:
        file_path = DOWNLOAD_DIR / filename
        if not file_path.exists():
            return jsonify({'error': 'File not found'}), 404

        return send_file(
            file_path,
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        logging.error(f"File serve error: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=False)
