from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os
import re
from pathlib import Path
import tempfile
import time
import logging
import sys



app = Flask(__name__)
CORS(app)


try:
    DOWNLOAD_DIR = Path("downloads")
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    logging.info(f"Download directory created at: {DOWNLOAD_DIR.resolve()}")
except Exception as e:
    logging.error(f"Failed to create download directory: {str(e)}")


def extract_video_id(url):
    """Extract YouTube video ID from URL"""
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

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = []

        
        video_formats = []
        for f in info.get('formats', []):
            if f.get('vcodec') != 'none' and f.get('height'):
                video_formats.append(f)

        quality_map = {}
        for f in video_formats:
            height = f.get('height')
            if height not in quality_map:
                quality_map[height] = f
            else:
                current = quality_map[height]
                if f.get('tbr', 0) > current.get('tbr', 0):
                    quality_map[height] = f

        common_resolutions = [2160, 1440, 1080, 720, 480, 360, 240, 144]

        for height in common_resolutions:
            if height in quality_map:
                f = quality_map[height]

                filesize = f.get('filesize') or f.get('filesize_approx', 0)

                if not filesize and f.get('tbr') and info.get('duration'):
                    duration = info.get('duration', 0)
                    filesize = int((f.get('tbr', 0) * duration * 1024) / 8)

                format_string = (
                    f"bestvideo[height={height}]+bestaudio/"
                    f"bestvideo[height<={height}]+bestaudio/"
                    f"best[height<={height}]"
                )

                formats.append({
                    'format_id': format_string,
                    'quality': f'{height}p',
                    'ext': 'mp4',
                    'filesize': filesize,
                    'filesize_str': format_bytes(filesize) if filesize else 'Estimated',
                    'fps': f.get('fps', 30),
                    'vcodec': f.get('vcodec', 'h264'),
                    'acodec': 'aac'
                })

        audio_formats = [
            f for f in info.get('formats', [])
            if f.get('acodec') != 'none' and f.get('vcodec') == 'none'
        ]

        if audio_formats:
            best_audio = max(audio_formats, key=lambda x: x.get('abr', 0))
            filesize = best_audio.get('filesize') or best_audio.get('filesize_approx', 0)

            formats.append({
                'format_id': 'bestaudio',
                'quality': 'Audio Only',
                'ext': 'mp3',
                'filesize': filesize,
                'filesize_str': format_bytes(filesize) if filesize else 'Unknown',
                'abr': best_audio.get('abr'),
                'acodec': best_audio.get('acodec')
            })

        return jsonify({
            'id': video_id,
            'title': info.get('title'),
            'thumbnail': info.get('thumbnail'),
            'duration': format_duration(info.get('duration', 0)),
            'duration_seconds': info.get('duration', 0),
            'uploader': info.get('uploader'),
            'view_count': info.get('view_count'),
            'formats': formats
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/download', methods=['POST'])
def download_video():
    """Download video in specified format"""
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
        
        ydl_opts = {
            'outtmpl': str(DOWNLOAD_DIR / f'{video_id}_%(title)s.%(ext)s'),
            # 'progress_hooks': [progress_hook],
            'quiet': False,
            'no_warnings': False,
        }
        
        # If audio only, extract audio
        if 'audio' in quality.lower() or format_id == 'bestaudio':
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        else:
            # For video formats - use the exact format string
            ydl_opts['format'] = format_id
            ydl_opts['merge_output_format'] = 'mp4'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }]
        
        logging.info("Starting yt_dlp download...")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            base_filename = ydl.prepare_filename(info)
            possible_files = [
                base_filename,
                base_filename.rsplit('.', 1)[0] + '.mp4',
                base_filename.rsplit('.', 1)[0] + '.mp3',
                base_filename.rsplit('.', 1)[0] + '.m4a',
                base_filename.rsplit('.', 1)[0] + '.webm',
            ]
            all_files = list(DOWNLOAD_DIR.glob(f'{video_id}_*'))
            downloaded_file = None
            for file_path in possible_files:
                if os.path.exists(file_path):
                    downloaded_file = file_path
                    break

            logging.info("Download finished")
            logging.info(f"Base filename: {base_filename}")
            logging.info(f"All files found: {all_files}")
            if not downloaded_file and all_files:
                downloaded_file = str(max(all_files, key=os.path.getctime))
            
            if not downloaded_file:
                return jsonify({'error': 'Download completed but file not found'}), 500
            return jsonify({
                'success': True,
                'filename': os.path.basename(downloaded_file),
                'file_path': downloaded_file,
                'download_id': video_id
            })
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/download-file/<filename>', methods=['GET'])
def download_file(filename):
    """Serve the downloaded file"""
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
        return jsonify({'error': str(e)}), 500

        
def format_duration(seconds):
    if not seconds:
        return '0:00'

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_bytes(size):
    if not size:
        return "Unknown"

    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)


if __name__ == '__main__':
    app.run(debug=False)
