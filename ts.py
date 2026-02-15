from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os
import re
from pathlib import Path
import tempfile
import threading
import time

app = Flask(__name__)
CORS(app)  # Enable CORS for Next.js frontend

# Create downloads directory
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Store download progress
download_progress = {}

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

def progress_hook(d):
    """Hook to track download progress"""
    if d['status'] == 'downloading':
        video_id = d.get('info_dict', {}).get('id', 'unknown')
        download_progress[video_id] = {
            'status': 'downloading',
            'percent': d.get('_percent_str', '0%'),
            'speed': d.get('_speed_str', 'N/A'),
            'eta': d.get('_eta_str', 'N/A')
        }
    elif d['status'] == 'finished':
        video_id = d.get('info_dict', {}).get('id', 'unknown')
        download_progress[video_id] = {
            'status': 'finished',
            'filename': d.get('filename')
        }

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'message': 'Backend is running'})

@app.route('/api/video-info', methods=['POST'])
def get_video_info():
    """Get video information without downloading"""
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        video_id = extract_video_id(url)
        if not video_id:
            return jsonify({'error': 'Invalid YouTube URL'}), 400
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Extract available formats
            formats = []
            
            # Get all video formats (including those without audio)
            video_formats = []
            for f in info.get('formats', []):
                if f.get('vcodec') != 'none' and f.get('height'):
                    video_formats.append(f)
            
            # Group by quality and get best for each resolution
            quality_map = {}
            for f in video_formats:
                height = f.get('height')
                if height not in quality_map:
                    quality_map[height] = f
                else:
                    # Prefer format with higher bitrate
                    current = quality_map[height]
                    if f.get('tbr', 0) > current.get('tbr', 0):
                        quality_map[height] = f
            
            # Create format options for common resolutions
            common_resolutions = [2160, 1440, 1080, 720, 480, 360, 240, 144]
            
            for height in common_resolutions:
                if height in quality_map:
                    f = quality_map[height]
                    filesize = f.get('filesize') or f.get('filesize_approx', 0)
                    
                    # Estimate filesize if not available
                    if not filesize and f.get('tbr') and info.get('duration'):
                        duration = info.get('duration', 0)
                        # tbr is in kbps, convert to bytes: (kbps * duration * 1024) / 8
                        filesize = int((f.get('tbr', 0) * duration * 1024) / 8)
                    
                    # For higher resolutions, video and audio are separate
                    # We need to merge them, so use a format expression
                    # Format: bestvideo[height=XXX]+bestaudio/best[height<=XXX]
                    # This ensures we get EXACTLY the height we want
                    format_string = f"bestvideo[height={height}]+bestaudio/bestvideo[height<={height}]+bestaudio/best[height<={height}]"
                    
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
            
            # Add audio-only option
            audio_formats = [f for f in info.get('formats', []) 
                           if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
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
        print(f"Error in get_video_info: {str(e)}")
        import traceback
        traceback.print_exc()
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
        
        print(f"Download request - URL: {url}")
        print(f"Format ID: {format_id}")
        print(f"Quality: {quality}")
        
        # Configure yt-dlp options
        ydl_opts = {
            'outtmpl': str(DOWNLOAD_DIR / f'{video_id}_%(title)s.%(ext)s'),
            'progress_hooks': [progress_hook],
            'quiet': False,
            'no_warnings': False,
        }
        
        # If audio only, extract audio
        if 'audio' in quality.lower() or format_id == 'bestaudio':
            print("Downloading audio only...")
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        else:
            # For video formats - use the exact format string
            print(f"Downloading video with format: {format_id}")
            ydl_opts['format'] = format_id
            # Ensure output is mp4
            ydl_opts['merge_output_format'] = 'mp4'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }]
        
        print(f"yt-dlp options: {ydl_opts}")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print("Starting download...")
            info = ydl.extract_info(url, download=True)
            print(f"Download complete. Looking for file...")
            
            # Find the downloaded file
            base_filename = ydl.prepare_filename(info)
            print(f"Base filename: {base_filename}")
            
            # Check for post-processed file
            possible_files = [
                base_filename,
                base_filename.rsplit('.', 1)[0] + '.mp4',
                base_filename.rsplit('.', 1)[0] + '.mp3',
                base_filename.rsplit('.', 1)[0] + '.m4a',
                base_filename.rsplit('.', 1)[0] + '.webm',
            ]
            
            # Also check all files in download directory
            all_files = list(DOWNLOAD_DIR.glob(f'{video_id}_*'))
            print(f"Files in download directory: {all_files}")
            
            downloaded_file = None
            for file_path in possible_files:
                print(f"Checking: {file_path}")
                if os.path.exists(file_path):
                    downloaded_file = file_path
                    print(f"Found file: {downloaded_file}")
                    break
            
            # If not found in expected locations, use the most recent file
            if not downloaded_file and all_files:
                downloaded_file = str(max(all_files, key=os.path.getctime))
                print(f"Using most recent file: {downloaded_file}")
            
            if not downloaded_file:
                return jsonify({'error': 'Download completed but file not found'}), 500
            
            return jsonify({
                'success': True,
                'filename': os.path.basename(downloaded_file),
                'file_path': downloaded_file,
                'download_id': video_id
            })
            
    except Exception as e:
        print(f"Error in download: {str(e)}")
        import traceback
        traceback.print_exc()
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

@app.route('/api/progress/<video_id>', methods=['GET'])
def get_progress(video_id):
    """Get download progress for a video"""
    progress = download_progress.get(video_id, {'status': 'not_found'})
    return jsonify(progress)

@app.route('/api/cleanup', methods=['POST'])
def cleanup_downloads():
    """Clean up old downloaded files"""
    try:
        data = request.get_json()
        filename = data.get('filename')
        
        if filename:
            file_path = DOWNLOAD_DIR / filename
            if file_path.exists():
                os.remove(file_path)
                return jsonify({'success': True, 'message': 'File deleted'})
        
        return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def format_bytes(bytes_size):
    """Convert bytes to human readable format"""
    if not bytes_size:
        return 'Unknown'
    
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} TB"

def format_duration(seconds):
    """Convert seconds to HH:MM:SS or MM:SS format"""
    if not seconds:
        return '0:00'
    
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"

if __name__ == '__main__':
    print("🚀 YouTube Downloader Backend Starting...")
    print("📍 API running on http://localhost:5000")
    print("🔗 Frontend should connect to http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)