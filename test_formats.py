#!/usr/bin/env python3
"""
Test script to verify yt-dlp format selection and downloads
This helps debug quality issues
"""

import yt_dlp
import sys

def test_formats(url):
    """Test what formats are available for a video"""
    
    print("=" * 70)
    print("TESTING YOUTUBE VIDEO FORMATS")
    print("=" * 70)
    print(f"\nURL: {url}\n")
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        
        print(f"Title: {info.get('title')}")
        print(f"Duration: {info.get('duration')} seconds")
        print(f"Uploader: {info.get('uploader')}\n")
        
        print("-" * 70)
        print("AVAILABLE VIDEO FORMATS:")
        print("-" * 70)
        
        # Get video formats
        video_formats = [f for f in info.get('formats', []) 
                        if f.get('vcodec') != 'none' and f.get('height')]
        
        # Group by height
        by_height = {}
        for f in video_formats:
            height = f.get('height')
            if height not in by_height:
                by_height[height] = []
            by_height[height].append(f)
        
        # Print sorted by quality
        for height in sorted(by_height.keys(), reverse=True):
            formats = by_height[height]
            print(f"\n{height}p Quality:")
            for f in formats[:3]:  # Show top 3 for each quality
                has_audio = f.get('acodec') != 'none'
                filesize = f.get('filesize') or f.get('filesize_approx', 0)
                size_mb = filesize / (1024*1024) if filesize else 0
                
                print(f"  Format ID: {f.get('format_id'):10s} | "
                      f"Codec: {f.get('vcodec', 'N/A'):15s} | "
                      f"FPS: {f.get('fps', 0):3.0f} | "
                      f"Audio: {'Yes' if has_audio else 'No':3s} | "
                      f"Size: {size_mb:6.1f} MB")
        
        print("\n" + "-" * 70)
        print("TESTING FORMAT STRINGS:")
        print("-" * 70)
        
        # Test format strings
        test_heights = [2160, 1440, 1080, 720, 480, 360]
        
        for height in test_heights:
            if height in by_height:
                # Test exact height match
                format_string = f"bestvideo[height={height}]+bestaudio/bestvideo[height<={height}]+bestaudio/best[height<={height}]"
                print(f"\n{height}p Format String:")
                print(f"  {format_string}")
                
                # Simulate what yt-dlp would select
                try:
                    ydl_test = {
                        'format': format_string,
                        'quiet': True,
                        'simulate': True,
                    }
                    with yt_dlp.YoutubeDL(ydl_test) as ydl2:
                        test_info = ydl2.extract_info(url, download=False)
                        selected_height = test_info.get('height', 'Unknown')
                        selected_format = test_info.get('format_id', 'Unknown')
                        print(f"  Would download: {selected_height}p (format: {selected_format})")
                except Exception as e:
                    print(f"  Error: {e}")

def test_download(url, quality):
    """Test downloading a specific quality"""
    
    print("\n" + "=" * 70)
    print(f"TEST DOWNLOAD - {quality}")
    print("=" * 70)
    
    # Map quality to format string
    if quality == '1080p':
        format_string = "bestvideo[height=1080]+bestaudio/bestvideo[height<=1080]+bestaudio/best[height<=1080]"
    elif quality == '720p':
        format_string = "bestvideo[height=720]+bestaudio/bestvideo[height<=720]+bestaudio/best[height<=720]"
    elif quality == '480p':
        format_string = "bestvideo[height=480]+bestaudio/best[height<=480]"
    else:
        format_string = "best"
    
    print(f"Format string: {format_string}\n")
    
    ydl_opts = {
        'format': format_string,
        'outtmpl': 'test_download_%(title)s.%(ext)s',
        'merge_output_format': 'mp4',
        'simulate': True,  # Don't actually download
        'quiet': False,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        
        print(f"Selected format ID: {info.get('format_id')}")
        print(f"Resolution: {info.get('width')}x{info.get('height')}")
        print(f"Video codec: {info.get('vcodec')}")
        print(f"Audio codec: {info.get('acodec')}")
        print(f"FPS: {info.get('fps')}")
        
        filesize = info.get('filesize') or info.get('filesize_approx', 0)
        if filesize:
            size_mb = filesize / (1024*1024)
            print(f"File size: {size_mb:.1f} MB")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python test_formats.py <youtube_url> [quality]")
        print("\nExample:")
        print("  python test_formats.py https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        print("  python test_formats.py https://www.youtube.com/watch?v=dQw4w9WgXcQ 1080p")
        sys.exit(1)
    
    url = sys.argv[1]
    
    # Show all available formats
    test_formats(url)
    
    # If quality specified, test that download
    if len(sys.argv) > 2:
        quality = sys.argv[2]
        test_download(url, quality)
    
    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)