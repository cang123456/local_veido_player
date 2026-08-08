# -*- coding: utf-8 -*-
"""
高性能视频流 HTTP 服务器
支持 Range 请求（断点续传）、多线程、优化的缓冲区
自带美观的播放器页面

使用方法:
    python app.py                              # 默认端口 9000
    python app.py -p 8080                      # 指定端口
    python app.py -d D:/Videos                 # 指定目录
    python app.py -b 0.0.0.0                   # 指定绑定地址
"""

import os
import sys
import io
import argparse
import mimetypes
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn

# 视频相关的 MIME 类型映射
VIDEO_MIME_TYPES = {
    '.mp4': 'video/mp4',
    '.mkv': 'video/x-matroska',
    '.avi': 'video/x-msvideo',
    '.mov': 'video/quicktime',
    '.wmv': 'video/x-ms-wmv',
    '.flv': 'video/x-flv',
    '.webm': 'video/webm',
    '.m4v': 'video/x-m4v',
    '.ts': 'video/mp2t',
    '.mts': 'video/mp2t',
    '.3gp': 'video/3gpp',
    '.rmvb': 'application/vnd.rn-realmedia-vbr',
    '.rm': 'application/vnd.rn-realmedia',
    '.vob': 'video/dvd',
    '.ogv': 'video/ogg',
}

# 音频 MIME 类型
AUDIO_MIME_TYPES = {
    '.mp3': 'audio/mpeg',
    '.wav': 'audio/wav',
    '.flac': 'audio/flac',
    '.aac': 'audio/aac',
    '.ogg': 'audio/ogg',
    '.wma': 'audio/x-ms-wma',
    '.m4a': 'audio/mp4',
}

# 缓冲区大小 - 64KB 提高传输效率
BUFFER_SIZE = 64 * 1024
# 默认端口
default_port=9001

def is_media_file(path):
    """判断是否为音视频文件"""
    ext = os.path.splitext(path)[1].lower()
    return ext in VIDEO_MIME_TYPES or ext in AUDIO_MIME_TYPES


def is_video_file(path):
    """判断是否为视频文件"""
    ext = os.path.splitext(path)[1].lower()
    return ext in VIDEO_MIME_TYPES


def format_file_size(size):
    """格式化文件大小"""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    else:
        return f"{size / (1024 * 1024 * 1024):.2f} GB"


class VideoRequestHandler(SimpleHTTPRequestHandler):
    """增强的请求处理器，支持 Range 请求、美观的播放器和目录列表"""

    def guess_type(self, path):
        ext = os.path.splitext(path)[1].lower()
        if ext in VIDEO_MIME_TYPES:
            return VIDEO_MIME_TYPES[ext]
        if ext in AUDIO_MIME_TYPES:
            return AUDIO_MIME_TYPES[ext]
        mime_type, _ = mimetypes.guess_type(path)
        return mime_type or 'application/octet-stream'

    def send_head(self):
        path = self.translate_path(self.path)

        if os.path.isdir(path):
            return self.render_directory_listing(path)

        if not os.path.exists(path):
            self.send_error(404, "File not found")
            return None

        # 检查是否请求播放器页面（带 ?play 参数）
        parsed_path = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed_path.query)
        if 'play' in query and is_media_file(path):
            return self.render_player_page(path, parsed_path.path)

        try:
            file_size = os.path.getsize(path)
            mime_type = self.guess_type(path)

            range_header = self.headers.get('Range')

            if range_header:
                range_match = range_header.strip().replace('bytes=', '')
                start, end = None, None

                if '-' in range_match:
                    parts = range_match.split('-', 1)
                    start = int(parts[0]) if parts[0] else None
                    end = int(parts[1]) if parts[1] else None

                if start is not None and start >= file_size:
                    self.send_response(416)
                    self.send_header('Content-Range', f'bytes */{file_size}')
                    self.end_headers()
                    return None

                if start is None:
                    start = max(0, file_size - (end or 0))
                    end = file_size - 1
                elif end is None or end >= file_size:
                    end = file_size - 1

                length = end - start + 1

                self.send_response(206)
                self.send_header('Content-Type', mime_type)
                self.send_header('Content-Length', str(length))
                self.send_header('Content-Range', f'bytes {start}-{end}/{file_size}')
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Cache-Control', 'public, max-age=3600')
                self.end_headers()

                f = open(path, 'rb')
                f.seek(start)
                return f

            else:
                self.send_response(200)
                self.send_header('Content-Type', mime_type)
                self.send_header('Content-Length', str(file_size))
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Cache-Control', 'public, max-age=3600')
                self.end_headers()

                return open(path, 'rb')

        except Exception as e:
            self.send_error(500, f"Server error: {e}")
            return None

    def copyfile(self, source, outputfile):
        try:
            while True:
                buf = source.read(BUFFER_SIZE)
                if not buf:
                    break
                outputfile.write(buf)
        except ConnectionResetError:
            pass

    def do_GET(self):
        f = None
        try:
            f = self.send_head()
            if f:
                self.copyfile(f, self.wfile)
        except ConnectionResetError:
            pass
        finally:
            if f:
                try:
                    f.close()
                except Exception:
                    pass

    # ==================== 美观的播放器页面 ====================
    def render_player_page(self, file_path, url_path):
        """渲染美观的播放器页面"""
        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        ext = os.path.splitext(file_name)[1].lower()
        is_video = ext in VIDEO_MIME_TYPES
        mime_type = self.guess_type(file_path)

        # 获取同目录下的媒体文件列表
        dir_path = os.path.dirname(file_path)
        dir_url = os.path.dirname(url_path.rstrip('/')) or '/'

        playlist_items = []
        try:
            all_files = sorted(os.listdir(dir_path), key=lambda a: a.lower())
            for name in all_files:
                full_path = os.path.join(dir_path, name)
                if os.path.isfile(full_path) and is_media_file(name):
                    item_url = urllib.parse.quote(name)
                    is_current = (name == file_name)
                    item_ext = os.path.splitext(name)[1].lower()
                    item_size = os.path.getsize(full_path)
                    icon = "🎬" if item_ext in VIDEO_MIME_TYPES else "🎵"
                    playlist_items.append({
                        'name': name,
                        'url': f'{item_url}?play=1',
                        'is_current': is_current,
                        'icon': icon,
                        'size': format_file_size(item_size),
                    })
        except Exception:
            pass

        html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{file_name} - AryPlayer</title>
<style>
:root {{
    --primary: #4A90E2;
    --primary-hover: #357ABD;
    --bg: #FAFAFA;
    --card-bg: #FFFFFF;
    --text-main: #1F2937;
    --text-sub: #6B7280;
    --text-light: #9CA3AF;
    --border: #E5E7EB;
    --border-light: #F3F4F6;
    --shadow-sm: 0 1px 2px rgba(0,0,0,0.04);
    --shadow: 0 4px 16px rgba(0,0,0,0.08);
    --shadow-lg: 0 8px 32px rgba(0,0,0,0.12);
    --radius: 12px;
    --radius-sm: 8px;
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{
    overflow-x: hidden;
    max-width: 100%;
}}
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: var(--bg);
    color: var(--text-main);
    min-height: 100vh;
    -webkit-font-smoothing: antialiased;
    overflow-x: hidden;
}}
.topbar {{
    background: var(--card-bg);
    border-bottom: 1px solid var(--border-light);
    position: sticky;
    top: 0;
    z-index: 100;
    box-shadow: var(--shadow-sm);
}}
.topbar-inner {{
    max-width: 1200px;
    margin: 0 auto;
    padding: 14px 24px;
    display: flex;
    align-items: center;
    gap: 16px;
}}
.logo {{
    display: flex;
    align-items: center;
    gap: 10px;
    font-weight: 700;
    font-size: 18px;
    color: var(--primary);
}}
.logo-icon {{
    width: 34px;
    height: 34px;
    background: linear-gradient(135deg, var(--primary), #6BA8EA);
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #fff;
    font-size: 18px;
    box-shadow: 0 2px 8px rgba(74,144,226,0.3);
}}
.back-btn {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 8px 16px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--card-bg);
    color: var(--text-sub);
    text-decoration: none;
    font-size: 14px;
    transition: all 0.2s ease;
    cursor: pointer;
}}
.back-btn:hover {{
    background: var(--border-light);
    color: var(--primary);
    border-color: var(--primary);
}}
.main {{
    max-width: 1200px;
    margin: 0 auto;
    padding: 24px;
    display: grid;
    grid-template-columns: minmax(0, 1fr) 320px;
    gap: 24px;
}}
@media (max-width: 900px) {{
    .main {{ grid-template-columns: minmax(0, 1fr); padding: 12px; gap: 12px; }}
    .topbar-inner {{ padding: 12px 16px; }}
    .info-section {{ padding: 16px; }}
    .file-title {{ font-size: 17px; }}
    .file-meta {{ gap: 8px; }}
    .meta-item {{ font-size: 12px; padding: 5px 10px; }}
    .download-btn {{ padding: 7px 14px; font-size: 13px; margin-left: 0; }}
    .transform-controls {{ padding: 10px 12px; gap: 6px; }}
    .ctrl-btn {{ padding: 6px 10px; font-size: 12px; }}
    .ctrl-label {{ display: none; }}
    .playlist-card {{ position: static; }}
    .playlist {{ max-height: 320px; }}
}}
@media (max-width: 480px) {{
    .main {{ padding: 8px; }}
    .topbar-inner {{ padding: 10px 12px; }}
    .logo {{ font-size: 16px; }}
    .logo-icon {{ width: 30px; height: 30px; font-size: 16px; }}
    .info-section {{ padding: 12px; }}
    .file-title {{ font-size: 15px; }}
    .player-wrapper video {{ max-width: 100%; }}
}}
.player-section {{
    display: flex;
    flex-direction: column;
    gap: 20px;
    min-width: 0;
}}
.player-card {{
    background: var(--card-bg);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    overflow: hidden;
}}
.player-wrapper {{
    width: 100%;
    background: #000;
    aspect-ratio: 16 / 9;
    display: flex;
    align-items: center;
    justify-content: center;
}}
.player-wrapper audio {{
    width: 100%;
    padding: 40px 24px;
}}
.player-wrapper video {{
    width: 100%;
    height: 100%;
    object-fit: contain;
    background: #000;
    max-width: 100%;
}}
.video-transform {{
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: transform 0.25s ease;
    transform-origin: center center;
    will-change: transform;
    backface-visibility: hidden;
}}
.video-transform.flip-h video::-webkit-media-controls {{
    transform: scaleX(-1) !important;
}}
.video-transform.flip-v video::-webkit-media-controls {{
    transform: scaleY(-1) !important;
}}
.video-transform.flip-h.flip-v video::-webkit-media-controls {{
    transform: scaleX(-1) scaleY(-1) !important;
}}
.info-section {{
    padding: 24px;
}}
.file-title {{
    font-size: 20px;
    font-weight: 600;
    color: var(--text-main);
    margin-bottom: 12px;
    line-height: 1.4;
    word-break: break-all;
}}
.file-meta {{
    display: flex;
    flex-wrap: wrap;
    gap: 16px;
    align-items: center;
}}
.meta-item {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    background: var(--border-light);
    border-radius: 20px;
    font-size: 13px;
    color: var(--text-sub);
}}
.meta-item .label {{ color: var(--text-light); }}
.download-btn {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 8px 18px;
    background: var(--primary);
    color: #fff;
    border-radius: var(--radius-sm);
    text-decoration: none;
    font-size: 14px;
    font-weight: 500;
    transition: all 0.2s ease;
    margin-left: auto;
}}
.download-btn:hover {{
    background: var(--primary-hover);
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(74,144,226,0.3);
}}

/* 播放列表 */
.playlist-card {{
    background: var(--card-bg);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    overflow: hidden;
    height: fit-content;
    position: sticky;
    top: 80px;
}}
.playlist-header {{
    padding: 18px 20px;
    border-bottom: 1px solid var(--border-light);
    display: flex;
    align-items: center;
    justify-content: space-between;
}}
.playlist-title {{
    font-size: 16px;
    font-weight: 600;
    color: var(--text-main);
    display: flex;
    align-items: center;
    gap: 8px;
}}
.playlist-count {{
    font-size: 13px;
    color: var(--text-light);
    font-weight: 400;
}}
.playlist {{
    list-style: none;
    max-height: 520px;
    overflow-y: auto;
    padding: 8px;
}}
.playlist::-webkit-scrollbar {{
    width: 6px;
}}
.playlist::-webkit-scrollbar-track {{
    background: transparent;
}}
.playlist::-webkit-scrollbar-thumb {{
    background: #D1D5DB;
    border-radius: 3px;
}}
.playlist::-webkit-scrollbar-thumb:hover {{
    background: #9CA3AF;
}}
.playlist-item {{
    padding: 12px;
    border-radius: var(--radius-sm);
    margin-bottom: 2px;
    cursor: pointer;
    transition: all 0.15s ease;
    text-decoration: none;
    display: block;
}}
.playlist-item:hover {{
    background: var(--border-light);
}}
.playlist-item.active {{
    background: linear-gradient(135deg, rgba(74,144,226,0.10), rgba(74,144,226,0.05));
    border: 1px solid rgba(74,144,226,0.2);
}}
.playlist-item-inner {{
    display: flex;
    align-items: center;
    gap: 12px;
}}
.item-icon {{
    width: 36px;
    height: 36px;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 16px;
    background: var(--border-light);
    flex-shrink: 0;
}}
.playlist-item.active .item-icon {{
    background: linear-gradient(135deg, var(--primary), #6BA8EA);
    color: #fff;
}}
.item-info {{
    flex: 1;
    min-width: 0;
}}
.item-name {{
    font-size: 14px;
    color: var(--text-main);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    margin-bottom: 3px;
}}
.playlist-item.active .item-name {{
    color: var(--primary);
    font-weight: 500;
}}
.item-size {{
    font-size: 12px;
    color: var(--text-light);
}}
.empty-state {{
    padding: 40px 20px;
    text-align: center;
    color: var(--text-light);
    font-size: 14px;
}}

/* 旧控制条移除 */

/* ==================== Bilibili 风格视频播放器自定义控制栏 ==================== */
.player-wrapper {{
    position: relative;
    width: 100%;
    aspect-ratio: 16/9;
    background: #000;
    overflow: hidden;
    border-radius: 12px;
}}
#playerCard.fs-active .player-wrapper {{
    flex: 1;
    aspect-ratio: auto;
    border-radius: 0;
}}
.video-transform {{
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: transform 0.25s ease;
    will-change: transform;
}}
#mediaPlayer {{
    width: 100%;
    height: 100%;
    object-fit: contain;
    background: #000;
    outline: none;
}}

/* 自定义控制栏容器 */
.custom-controls {{
    position: absolute;
    inset: 0;
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.25s ease;
    z-index: 10;
}}
.player-wrapper.cc-show-controls .custom-controls {{
    opacity: 1;
    pointer-events: auto;
}}
/* 控制栏激活期间底部有渐变遮罩 */
.cc-bottom {{
    position: absolute;
    left: 0; right: 0; bottom: 0;
    padding: 40px 18px 14px;
    background: linear-gradient(transparent, rgba(0,0,0,0.65) 70%, rgba(0,0,0,0.75));
    pointer-events: auto;
}}
.cc-top {{
    position: absolute;
    left: 0; right: 0; top: 0;
    padding: 14px 18px 40px;
    background: linear-gradient(rgba(0,0,0,0.55), transparent);
    display: flex;
    align-items: center;
    gap: 12px;
    pointer-events: auto;
}}
.cc-back {{
    color: #fff !important;
    width: 36px !important;
    height: 36px !important;
    padding: 0 !important;
    border-radius: 50% !important;
    background: rgba(0,0,0,0.35);
    display: inline-flex !important;
    align-items: center;
    justify-content: center;
    font-size: 0 !important;
}}
.cc-back:hover {{ background: rgba(0,0,0,0.55) !important; border-color: transparent !important; }}
.cc-title {{
    flex: 1;
    color: #fff;
    font-size: 14px;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    text-shadow: 0 1px 2px rgba(0,0,0,0.5);
}}

/* 中心大播放按钮 */
.cc-center-play {{
    position: absolute;
    top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    width: 72px;
    height: 72px;
    border-radius: 50%;
    background: rgba(0,0,0,0.55);
    border: 2px solid rgba(255,255,255,0.85);
    color: #fff;
    font-size: 28px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: all 0.2s ease;
    pointer-events: auto;
    padding-left: 6px;
    opacity: 0;
}}
.player-wrapper.cc-paused .cc-center-play {{ opacity: 1; }}
.cc-center-play:hover {{ transform: translate(-50%, -50%) scale(1.1); background: rgba(74,144,226,0.7); }}

/* 进度条 */
.cc-progress-wrap {{
    position: relative;
    padding: 8px 0 10px;
    cursor: pointer;
}}
.cc-progress-bar {{
    position: relative;
    height: 4px;
    background: rgba(255,255,255,0.25);
    border-radius: 2px;
    transition: height 0.2s ease;
}}
.cc-progress-wrap:hover .cc-progress-bar {{
    height: 6px;
}}
.cc-progress-buffered {{
    position: absolute;
    top: 0; left: 0;
    height: 100%;
    background: rgba(255,255,255,0.4);
    border-radius: 2px;
}}
.cc-progress-played {{
    position: absolute;
    top: 0; left: 0;
    height: 100%;
    background: linear-gradient(90deg, #4A90E2, #6BA8EA);
    border-radius: 2px;
}}
.cc-progress-thumb {{
    position: absolute;
    top: 50%;
    left: 0%;
    width: 14px;
    height: 14px;
    background: #fff;
    border-radius: 50%;
    transform: translate(-50%, -50%) scale(0);
    box-shadow: 0 0 6px rgba(0,0,0,0.4);
    transition: transform 0.18s ease;
    pointer-events: none;
}}
.cc-progress-wrap:hover .cc-progress-thumb,
.cc-progress-wrap.dragging .cc-progress-thumb {{
    transform: translate(-50%, -50%) scale(1);
}}
.cc-progress-tip {{
    position: absolute;
    bottom: 22px;
    left: 0;
    transform: translateX(-50%);
    background: rgba(0,0,0,0.8);
    color: #fff;
    font-size: 12px;
    padding: 3px 8px;
    border-radius: 4px;
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.15s ease;
    white-space: nowrap;
}}
.cc-progress-wrap:hover .cc-progress-tip,
.cc-progress-wrap.dragging .cc-progress-tip {{
    opacity: 1;
}}

/* 按钮行 */
.cc-btn-row {{
    display: flex;
    align-items: center;
    gap: 6px;
    padding-top: 2px;
}}
.cc-icon-btn {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 36px;
    height: 36px;
    padding: 0 10px;
    background: transparent;
    border: none;
    color: #fff;
    font-size: 17px;
    cursor: pointer;
    border-radius: 6px;
    transition: background 0.18s ease;
    white-space: nowrap;
}}
.cc-icon-btn:hover {{
    background: rgba(255,255,255,0.15);
}}
.cc-icon-btn.active {{
    color: #4A90E2;
}}

.cc-time {{
    color: #fff;
    font-size: 13px;
    font-variant-numeric: tabular-nums;
    margin: 0 6px;
    opacity: 0.92;
}}
.cc-time-sep {{
    opacity: 0.5;
    margin: 0 3px;
}}

/* 音量 */
.cc-vol-wrap {{
    display: flex;
    align-items: center;
    gap: 2px;
}}
.cc-vol-bar {{
    position: relative;
    width: 0;
    height: 4px;
    background: rgba(255,255,255,0.3);
    border-radius: 2px;
    cursor: pointer;
    overflow: visible;
    transition: width 0.25s ease, margin 0.25s ease;
}}
.cc-vol-wrap:hover .cc-vol-bar,
.cc-vol-bar.dragging {{
    width: 80px;
    margin-right: 10px;
}}
.cc-vol-inner {{
    position: absolute;
    top: 0; left: 0;
    height: 100%;
    background: #fff;
    border-radius: 2px;
    width: 80%;
}}
.cc-vol-thumb {{
    position: absolute;
    top: 50%; left: 80%;
    width: 12px;
    height: 12px;
    background: #fff;
    border-radius: 50%;
    transform: translate(-50%, -50%) scale(0);
    transition: transform 0.18s ease;
    pointer-events: none;
}}
.cc-vol-wrap:hover .cc-vol-thumb,
.cc-vol-bar.dragging .cc-vol-thumb {{
    transform: translate(-50%, -50%) scale(1);
}}
.cc-spacer {{ flex: 1; }}

/* 画面调整按钮 */
.cc-adjust {{
    display: flex;
    gap: 2px;
    margin-right: 4px;
}}
.cc-adjust .cc-icon-btn {{
    font-size: 15px;
    min-width: 32px;
    height: 32px;
    padding: 0 6px;
}}
.cc-fullscreen {{
    font-size: 17px;
    padding-left: 12px !important;
}}

/* 加载提示 */
.cc-loading {{
    position: absolute;
    top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    display: none;
    z-index: 5;
}}
.cc-loading.show {{ display: block; }}
.cc-loading-spinner {{
    width: 48px;
    height: 48px;
    border: 3px solid rgba(255,255,255,0.25);
    border-top-color: #fff;
    border-radius: 50%;
    animation: ccSpin 0.9s linear infinite;
}}
@keyframes ccSpin {{ to {{ transform: rotate(360deg); }} }}

/* 快进预览提示 */
.cc-seek-tip {{
    position: absolute;
    top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    background: rgba(0,0,0,0.7);
    color: #fff;
    padding: 14px 24px;
    border-radius: 10px;
    font-size: 18px;
    font-weight: 500;
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.2s ease;
    z-index: 8;
    white-space: nowrap;
}}
.cc-seek-tip.show {{ opacity: 1; }}

/* SVG 图标基础样式 */
.cc-icon-btn svg,
.cc-back svg,
.cc-center-play svg {{
    width: 22px;
    height: 22px;
    fill: currentColor;
    display: block;
}}
.cc-back svg {{
    width: 20px;
    height: 20px;
}}
.cc-center-play svg {{
    width: 32px;
    height: 32px;
}}

/* 设置面板 */
.cc-settings-wrap {{
    position: relative;
}}
.cc-settings-panel {{
    position: absolute;
    bottom: 50px;
    right: 0;
    min-width: 180px;
    background: rgba(30,30,30,0.92);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border-radius: 10px;
    padding: 8px;
    display: none;
    box-shadow: 0 8px 32px rgba(0,0,0,0.4);
    border: 1px solid rgba(255,255,255,0.1);
    z-index: 20;
}}
.cc-settings-panel.show {{
    display: block;
}}
.cc-settings-title {{
    color: rgba(255,255,255,0.5);
    font-size: 12px;
    padding: 6px 12px 8px;
    border-bottom: 1px solid rgba(255,255,255,0.1);
    margin-bottom: 4px;
}}
.cc-settings-item {{
    display: flex;
    align-items: center;
    gap: 12px;
    width: 100%;
    padding: 9px 12px;
    background: transparent;
    border: none;
    border-radius: 6px;
    color: #fff;
    font-size: 13px;
    cursor: pointer;
    transition: background 0.15s ease;
    text-align: left;
}}
.cc-settings-item:hover {{
    background: rgba(255,255,255,0.1);
}}
.cc-settings-item.active {{
    background: rgba(74,144,226,0.25);
    color: #6BA8EA;
}}
.cc-settings-icon {{
    display: inline-flex;
    width: 20px;
    height: 20px;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
}}
.cc-settings-icon svg {{
    width: 20px;
    height: 20px;
    fill: currentColor;
}}

/* 全屏样式 */
#playerCard.fs-active .cc-back {{ display: inline-flex !important; }}
#playerCard.fs-active .cc-title {{ font-size: 15px; }}
#playerCard.fs-active .cc-bottom {{ padding: 50px 28px 20px; }}
#playerCard.fs-active .cc-top {{ padding: 20px 28px 60px; }}
#playerCard.fs-active .cc-vol-bar {{ width: 80px; margin-right: 10px; }}
#playerCard.fs-active .cc-vol-thumb {{ transform: translate(-50%, -50%) scale(1); }}

/* 移动端优化 */
@media (max-width: 768px) {{
    .player-wrapper {{ border-radius: 0; }}
    .cc-vol-wrap {{ display: none; }}
    .cc-title {{ font-size: 12px; }}
    .cc-bottom {{ padding: 30px 12px 10px; }}
    .cc-top {{ padding: 10px 12px 30px; }}
    .cc-center-play {{ width: 60px; height: 60px; }}
    .cc-center-play svg {{ width: 26px; height: 26px; }}
    .cc-icon-btn svg {{ width: 20px; height: 20px; }}
    .cc-settings-panel {{
        bottom: 56px;
        left: auto;
        right: 0;
        min-width: 170px;
    }}
}}
@media (max-width: 480px) {{
    .cc-icon-btn {{ min-width: 32px; height: 32px; font-size: 15px; padding: 0 8px; }}
    .cc-time {{ font-size: 11px; margin: 0 2px; }}
}}

/* 旋转翻转CSS — 抵消控制条反向翻转 */
.player-wrapper {{ overflow: hidden; }}
#playerCard.fs-active {{
    position: fixed;
    top: 0; left: 0;
    width: 100vw;
    height: 100vh;
    z-index: 9999;
    border-radius: 0;
    max-width: none;
    display: flex;
    flex-direction: column;
    background: #000;
}}
#playerCard.fs-active.fs-landscape {{
    top: 0; left: 0;
    width: 100vh;
    height: 100vw;
    transform: rotate(90deg) translateY(-100%);
    transform-origin: top left;
}}
#playerCard.fs-active .info-section {{ display: none; }}

</style>
</head>
<body>
<header class="topbar">
    <div class="topbar-inner">
        <div class="logo">
            <div class="logo-icon">▶</div>
            AryPlayer
        </div>
        <a href="{dir_url}/" class="back-btn">← 返回目录</a>
    </div>
</header>

<main class="main">
    <section class="player-section">
        <div class="player-card" id="playerCard">
            <div class="player-wrapper" id="playerWrapper">
                {"<div class=\"video-transform\" id=\"videoTransform\"><video id=\"mediaPlayer\" autoplay preload=\"metadata\" playsinline webkit-playsinline x5-playsinline x5-video-player-type=\"h5\" x5-video-player-fullscreen=\"false\">" if is_video else "<audio id=\"mediaPlayer\" controls autoplay preload=\"metadata\">"}
                    <source src="{url_path}" type="{mime_type}">
                    您的浏览器不支持该媒体格式。
                {"</video></div>" if is_video else "</audio>"}

                {"""<!-- Bilibili 风格自定义控制栏 -->
                <div class="custom-controls" id="customControls">

                    <!-- 顶部栏：返回 + 标题 -->
                    <div class="cc-top">
                        <button type="button" class="cc-icon-btn cc-back" id="ccBack" onclick="history.length>1?history.back():window.location.href='{dir_url}/'" title="返回"></button>
                        <div class="cc-title">{file_name}</div>
                    </div>

                    <!-- 中心大播放按钮（暂停时显示） -->
                    <button type="button" class="cc-center-play" id="ccCenterPlay" aria-label="播放"></button>

                    <!-- 底部控制层 -->
                    <div class="cc-bottom">

                        <!-- 进度条 -->
                        <div class="cc-progress-wrap" id="ccProgressWrap">
                            <div class="cc-progress-bar" id="ccProgressBar">
                                <div class="cc-progress-buffered" id="ccProgressBuffered"></div>
                                <div class="cc-progress-played" id="ccProgressPlayed"></div>
                                <div class="cc-progress-thumb" id="ccProgressThumb"></div>
                            </div>
                            <div class="cc-progress-tip" id="ccProgressTip">00:00</div>
                        </div>

                        <!-- 按钮行 -->
                        <div class="cc-btn-row">
                            <button type="button" class="cc-icon-btn" id="ccPrevBtn" title="上一个"></button>
                            <button type="button" class="cc-icon-btn" id="ccPlayBtn" title="播放/暂停"></button>
                            <button type="button" class="cc-icon-btn" id="ccNextBtn" title="下一个"></button>

                            <div class="cc-time">
                                <span id="ccCurTime">00:00</span>
                                <span class="cc-time-sep">/</span>
                                <span id="ccDurTime">00:00</span>
                            </div>

                            <div class="cc-vol-wrap" id="ccVolWrap">
                                <button type="button" class="cc-icon-btn" id="ccVolBtn" title="音量"></button>
                                <div class="cc-vol-bar" id="ccVolBar">
                                    <div class="cc-vol-inner" id="ccVolInner"></div>
                                    <div class="cc-vol-thumb" id="ccVolThumb"></div>
                                </div>
                            </div>

                            <div class="cc-spacer"></div>

                            <!-- 设置（画面调整） -->
                            <div class="cc-settings-wrap" id="ccSettingsWrap">
                                <button type="button" class="cc-icon-btn" id="ccSettingsBtn" title="设置"></button>
                                <div class="cc-settings-panel" id="ccSettingsPanel">
                                    <div class="cc-settings-title">画面调整</div>
                                    <button type="button" class="cc-settings-item" data-action="rotate-left">
                                        <span class="cc-settings-icon" id="iconRotateLeft"></span>
                                        <span>左转 90°</span>
                                    </button>
                                    <button type="button" class="cc-settings-item" data-action="rotate-right">
                                        <span class="cc-settings-icon" id="iconRotateRight"></span>
                                        <span>右转 90°</span>
                                    </button>
                                    <button type="button" class="cc-settings-item" id="btnFlipH" data-action="flip-h">
                                        <span class="cc-settings-icon" id="iconFlipH"></span>
                                        <span>水平翻转</span>
                                    </button>
                                    <button type="button" class="cc-settings-item" id="btnFlipV" data-action="flip-v">
                                        <span class="cc-settings-icon" id="iconFlipV"></span>
                                        <span>垂直翻转</span>
                                    </button>
                                    <button type="button" class="cc-settings-item" data-action="reset">
                                        <span class="cc-settings-icon" id="iconReset"></span>
                                        <span>重置</span>
                                    </button>
                                </div>
                            </div>

                            <button type="button" class="cc-icon-btn cc-fullscreen" id="btnFullscreen" title="全屏"></button>
                        </div>
                    </div>
                </div>
                <!-- 手势预览提示 -->
                <div class="cc-seek-tip" id="ccSeekTip"></div>
                <!-- 加载提示 -->
                <div class="cc-loading" id="ccLoading">
                    <div class="cc-loading-spinner"></div>
                </div>""" if is_video else ""}
            </div>
            <div class="info-section">
                <h1 class="file-title">{file_name}</h1>
                <div class="file-meta">
                    <span class="meta-item">
                        <span class="label">类型</span>
                        {"视频" if is_video else "音频"}
                    </span>
                    <span class="meta-item">
                        <span class="label">大小</span>
                        {format_file_size(file_size)}
                    </span>
                    <span class="meta-item">
                        <span class="label">格式</span>
                        {ext.upper()[1:]}
                    </span>
                    <a href="{url_path}" class="download-btn" download>
                        ⬇ 下载文件
                    </a>
                </div>
            </div>
        </div>
    </section>

    <aside>
        <div class="playlist-card">
            <div class="playlist-header">
                <div class="playlist-title">
                    📋 播放列表
                    <span class="playlist-count">({len(playlist_items)} 个文件)</span>
                </div>
            </div>
            <ul class="playlist">
                {"".join(f'''
                <a href="{item['url']}" class="playlist-item {"active" if item["is_current"] else ""}">
                    <li>
                        <div class="playlist-item-inner">
                            <div class="item-icon">{item["icon"]}</div>
                            <div class="item-info">
                                <div class="item-name">{item["name"]}</div>
                                <div class="item-size">{item["size"]}</div>
                            </div>
                        </div>
                    </li>
                </a>
                ''' for item in playlist_items) if playlist_items else '<li class="empty-state">暂无其他媒体文件</li>'}
            </ul>
        </div>
    </aside>
</main>

<script>
(function() {{
'use strict';

// ===== 全局变量 =====
var video = document.getElementById('mediaPlayer');
var wrapper = document.getElementById('playerWrapper');
if (!wrapper || !video) {{ // 音频不走这里
    // 音频：仍保留原生逻辑
    return;
}}
var controls = document.getElementById('customControls');
var playBtn = document.getElementById('ccPlayBtn');
var centerPlay = document.getElementById('ccCenterPlay');
var curTimeEl = document.getElementById('ccCurTime');
var durTimeEl = document.getElementById('ccDurTime');
var progressWrap = document.getElementById('ccProgressWrap');
var progressBar = document.getElementById('ccProgressBar');
var progressPlayed = document.getElementById('ccProgressPlayed');
var progressBuffered = document.getElementById('ccProgressBuffered');
var progressThumb = document.getElementById('ccProgressThumb');
var progressTip = document.getElementById('ccProgressTip');
var volBtn = document.getElementById('ccVolBtn');
var volBar = document.getElementById('ccVolInner').parentNode;
var volInner = document.getElementById('ccVolInner');
var volThumb = document.getElementById('ccVolThumb');
var loadingEl = document.getElementById('ccLoading');
var seekTip = document.getElementById('ccSeekTip');

var rotation = 0;
var flipH = false;
var flipV = false;

// ===== SVG 图标集 =====
var ICONS = {{
    play: '<svg viewBox="0 0 24 24"><polygon points="6,4 20,12 6,20"/></svg>',
    pause: '<svg viewBox="0 0 24 24"><rect x="5" y="4" width="4" height="16"/><rect x="15" y="4" width="4" height="16"/></svg>',
    prev: '<svg viewBox="0 0 24 24"><polygon points="19,20 10,12 19,4"/><rect x="5" y="4" width="2" height="16"/></svg>',
    next: '<svg viewBox="0 0 24 24"><polygon points="5,4 14,12 5,20"/><rect x="17" y="4" width="2" height="16"/></svg>',
    back: '<svg viewBox="0 0 24 24"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z"/></svg>',
    volHigh: '<svg viewBox="0 0 24 24"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z"/></svg>',
    volMute: '<svg viewBox="0 0 24 24"><path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4L9.91 6.09 12 8.18V4z"/></svg>',
    settings: '<svg viewBox="0 0 24 24"><path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94L14.4 2.81c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41L9.25 5.35C8.66 5.59 8.12 5.92 7.63 6.29L5.24 5.33c-.22-.08-.47 0-.59.22L2.74 8.87C2.62 9.08 2.66 9.34 2.86 9.48l2.03 1.58C4.84 11.36 4.8 11.69 4.8 12s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"/></svg>',
    fullscreen: '<svg viewBox="0 0 24 24"><path d="M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z"/></svg>',
    fullscreenExit: '<svg viewBox="0 0 24 24"><path d="M5 16h3v3h2v-5H5v2zm3-8H5v2h5V5H8v3zm6 11h2v-3h3v-2h-5v5zm2-11V5h-2v5h5V8h-3z"/></svg>',
    rotateLeft: '<svg viewBox="0 0 24 24"><path d="M12 5V1L7 6l5 5V7c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z"/></svg>',
    rotateRight: '<svg viewBox="0 0 24 24"><path d="M12 5V1l5 5-5 5V7c-3.31 0-6 2.69-6 6s2.69 6 6 6 6-2.69 6-6h2c0 4.42-3.58 8-8 8s-8-3.58-8-8 3.58-8 8-8z" transform="scale(-1,1) translate(-24,0)"/></svg>',
    flipH: '<svg viewBox="0 0 24 24"><path d="M12 6.99L20 17.01 4 17.01z"/></svg>',
    flipV: '<svg viewBox="0 0 24 24"><path d="M12 6.99L20 17.01 4 17.01z" transform="rotate(90 12 12)"/></svg>',
    reset: '<svg viewBox="0 0 24 24"><path d="M12 5V1L7 6l5 5V7c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z"/></svg>'
}};

// 注入所有图标
function injectIcons() {{
    var map = {{
        'ccBack': ICONS.back,
        'ccCenterPlay': ICONS.play,
        'ccPrevBtn': ICONS.prev,
        'ccPlayBtn': ICONS.play,
        'ccNextBtn': ICONS.next,
        'ccVolBtn': ICONS.volHigh,
        'ccSettingsBtn': ICONS.settings,
        'btnFullscreen': ICONS.fullscreen,
        'iconRotateLeft': ICONS.rotateLeft,
        'iconRotateRight': ICONS.rotateRight,
        'iconFlipH': ICONS.flipH,
        'iconFlipV': ICONS.flipV,
        'iconReset': ICONS.reset
    }};
    for (var id in map) {{
        var el = document.getElementById(id);
        if (el) el.innerHTML = map[id];
    }}
}}
injectIcons();

// ===== 工具函数 =====
function fmtTime(sec) {{
    if (!isFinite(sec) || sec < 0) sec = 0;
    var s = Math.floor(sec % 60);
    var m = Math.floor((sec / 60) % 60);
    var h = Math.floor(sec / 3600);
    var str = (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
    if (h > 0) str = h + ':' + (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
    return str;
}}

// ===== 控制栏显示/隐藏 =====
var hideTimer = null;
function showControls() {{
    wrapper.classList.add('cc-show-controls');
    clearTimeout(hideTimer);
    hideTimer = setTimeout(hideControls, 5000);
}}
function hideControls() {{
    if (video.paused) return; // 暂停不隐藏
    wrapper.classList.remove('cc-show-controls');
}}
wrapper.addEventListener('mousemove', showControls);
wrapper.addEventListener('mouseenter', showControls);
wrapper.addEventListener('mouseleave', function() {{
    if (!video.paused) wrapper.classList.remove('cc-show-controls');
}});

// ===== 播放控制 =====
function updatePlayUI() {{
    var paused = video.paused;
    playBtn.innerHTML = paused ? ICONS.play : ICONS.pause;
    centerPlay.innerHTML = paused ? ICONS.play : ICONS.pause;
    wrapper.classList.toggle('cc-paused', paused);
    if (paused) showControls(); else hideControls();
}}
function togglePlay() {{
    if (video.paused) {{ video.play(); }} else {{ video.pause(); }}
}}
playBtn.addEventListener('click', togglePlay);
centerPlay.addEventListener('click', togglePlay);
video.addEventListener('play', updatePlayUI);
video.addEventListener('pause', updatePlayUI);

// ===== 单击/双击识别（B站风格）=====
var clickTimer = null;
var lastClick = 0;
var touchStartX = 0, touchStartY = 0, touchStartTime = 0, touchStartCT = 0;
var touchMoved = false, seekTouchMode = false;
var isTouch = 'ontouchstart' in window;

wrapper.addEventListener('click', function(e) {{
    // 点击控件区域：重置定时器但不执行单击/双击逻辑
    if (e.target.closest('.custom-controls')) {{
        showControls();
        return;
    }}
    if (e.target.closest('.cc-loading')) return;
    // 双击检测
    var now = Date.now();
    if (now - lastClick < 280) {{
        // 双击 = 播放/暂停
        clearTimeout(clickTimer);
        lastClick = 0;
        togglePlay();
    }} else {{
        lastClick = now;
        clearTimeout(clickTimer);
        clickTimer = setTimeout(function() {{
            // 单击 = 显示/隐藏控制栏
            if (wrapper.classList.contains('cc-show-controls')) {{
                if (!video.paused) wrapper.classList.remove('cc-show-controls');
            }} else {{
                showControls();
            }}
        }}, 290);
    }}
}});

// ===== 时间更新 =====
video.addEventListener('loadedmetadata', function() {{
    durTimeEl.textContent = fmtTime(video.duration);
    updateVolumeUI();
    updateTransform();
}});
video.addEventListener('timeupdate', function() {{
    var dur = video.duration || 0;
    var ct = video.currentTime || 0;
    var pct = dur > 0 ? (ct / dur) * 100 : 0;
    progressPlayed.style.width = pct + '%';
    progressThumb.style.left = pct + '%';
    curTimeEl.textContent = fmtTime(ct);
}});
video.addEventListener('progress', function() {{
    try {{
        if (video.buffered.length) {{
            var end = video.buffered.end(video.buffered.length - 1);
            var pct = (end / (video.duration || 1)) * 100;
            progressBuffered.style.width = pct + '%';
        }}
    }} catch(e) {{}}
}});
video.addEventListener('waiting', function() {{ loadingEl.classList.add('show'); }});
video.addEventListener('playing', function() {{ loadingEl.classList.remove('show'); }});
video.addEventListener('canplay', function() {{ loadingEl.classList.remove('show'); }});
video.addEventListener('loadstart', function() {{ loadingEl.classList.add('show'); }});

// ===== 进度条：点击 + 拖拽 =====
var progDragging = false;
function getProgressPct(clientX) {{
    var rect = progressBar.getBoundingClientRect();
    var x = Math.max(0, Math.min(rect.width, clientX - rect.left));
    return rect.width > 0 ? x / rect.width : 0;
}}
function handleProgressDown(e) {{
    progDragging = true;
    progressWrap.classList.add('dragging');
    handleProgressMove(e);
}}
function handleProgressMove(e) {{
    if (!progDragging && e.type !== 'click' && e.type !== 'mousemove') return;
    var cx = e.clientX;
    if (e.touches && e.touches[0]) cx = e.touches[0].clientX;
    if (e.changedTouches && e.changedTouches[0] && cx === undefined) cx = e.changedTouches[0].clientX;
    var pct = getProgressPct(cx);
    // 显示tip
    var rect = progressWrap.getBoundingClientRect();
    var tipX = (cx - rect.left);
    progressTip.style.left = tipX + 'px';
    var dur = video.duration || 0;
    var targetT = pct * dur;
    progressTip.textContent = fmtTime(targetT);
    if (progDragging) {{
        progressPlayed.style.width = (pct * 100) + '%';
        progressThumb.style.left = (pct * 100) + '%';
    }}
}}
function handleProgressUp(e) {{
    if (!progDragging) return;
    var cx = e.clientX;
    if (e.changedTouches && e.changedTouches[0]) cx = e.changedTouches[0].clientX;
    var pct = getProgressPct(cx);
    var dur = video.duration || 0;
    video.currentTime = Math.max(0, Math.min(dur, pct * dur));
    progDragging = false;
    progressWrap.classList.remove('dragging');
}}
progressWrap.addEventListener('mousedown', handleProgressDown);
document.addEventListener('mousemove', function(e) {{
    if (progDragging) handleProgressMove(e);
    else if (e.target === progressWrap || progressWrap.contains(e.target)) handleProgressMove(e);
}});
document.addEventListener('mouseup', handleProgressUp);
progressWrap.addEventListener('touchstart', handleProgressDown, {{passive: true}});
progressWrap.addEventListener('touchmove', function(e) {{ handleProgressMove(e); }}, {{passive: true}});
progressWrap.addEventListener('touchend', handleProgressUp);

// ===== 音量控制 =====
function updateVolumeUI() {{
    var v = video.muted ? 0 : video.volume;
    volInner.style.width = (v * 100) + '%';
    volThumb.style.left = (v * 100) + '%';
    volBtn.innerHTML = (v === 0) ? ICONS.volMute : ICONS.volHigh;
}}
video.addEventListener('volumechange', updateVolumeUI);
volBtn.addEventListener('click', function() {{
    video.muted = !video.muted;
    if (!video.muted && video.volume === 0) video.volume = 0.6;
}});
var volDragging = false;
function getVolPct(clientX) {{
    var rect = volBar.getBoundingClientRect();
    var x = Math.max(0, Math.min(rect.width, clientX - rect.left));
    return rect.width > 0 ? x / rect.width : video.volume;
}}
function handleVolDown(e) {{
    volDragging = true;
    volBar.classList.add('dragging');
    handleVolMove(e);
}}
function handleVolMove(e) {{
    if (!volDragging) return;
    var cx = e.clientX;
    if (e.touches && e.touches[0]) cx = e.touches[0].clientX;
    var v = getVolPct(cx);
    video.volume = Math.max(0, Math.min(1, v));
    video.muted = v === 0;
}}
function handleVolUp() {{
    volDragging = false;
    volBar.classList.remove('dragging');
}}
volBar.addEventListener('mousedown', handleVolDown);
document.addEventListener('mousemove', function(e) {{ if (volDragging) handleVolMove(e); }});
document.addEventListener('mouseup', handleVolUp);
volBar.addEventListener('touchstart', handleVolDown, {{passive: true}});
volBar.addEventListener('touchmove', handleVolMove, {{passive: true}});
volBar.addEventListener('touchend', handleVolUp);

// ===== 画面旋转与翻转 =====
function updateTransform() {{
    var container = document.getElementById('videoTransform');
    if (!container) return;
    var t = 'rotate(' + rotation + 'deg)';
    if (flipH) t += ' scaleX(-1)';
    if (flipV) t += ' scaleY(-1)';
    container.style.transform = t;
    if (rotation === 90 || rotation === 270) {{
        video.style.width = 'auto';
        video.style.height = '100%';
    }} else {{
        video.style.width = '100%';
        video.style.height = '100%';
    }}
}}
var fsBtnEl = document.getElementById('btnFullscreen');
if (fsBtnEl) {{
    fsBtnEl.addEventListener('click', function(e) {{
        e.stopPropagation();
        toggleFullscreen();
    }});
}}

// ===== 全屏 =====
function toggleFullscreen() {{
    var card = document.getElementById('playerCard');
    if (!card) return;
    if (!card.classList.contains('fs-active')) enterFullscreen(card);
    else exitFullscreen(card);
}}
function enterFullscreen(card) {{
    var isPortrait = window.innerHeight > window.innerWidth;
    card.classList.add('fs-active');
    if (isPortrait) card.classList.add('fs-landscape');
    if (card.requestFullscreen) card.requestFullscreen().catch(function(){{}});
    else if (card.webkitRequestFullscreen) {{ try {{ card.webkitRequestFullscreen(); }} catch(e){{}} }}
    if (screen.orientation && screen.orientation.lock) screen.orientation.lock('landscape').catch(function(){{}});
    var fsBtn = document.getElementById('btnFullscreen');
    if (fsBtn) fsBtn.innerHTML = ICONS.fullscreenExit;
    updateTransform();
    showControls();
}}
function exitFullscreen(card) {{
    card.classList.remove('fs-active', 'fs-landscape');
    if (document.fullscreenElement) document.exitFullscreen();
    else if (document.webkitFullscreenElement) document.webkitExitFullscreen();
    if (screen.orientation && screen.orientation.unlock) screen.orientation.unlock();
    var fsBtn = document.getElementById('btnFullscreen');
    if (fsBtn) fsBtn.innerHTML = ICONS.fullscreen;
    updateTransform();
    hideSettingsPanel();
}}
document.addEventListener('fullscreenchange', function() {{
    var card = document.getElementById('playerCard');
    if (!document.fullscreenElement && card && card.classList.contains('fs-active')) {{
        card.classList.remove('fs-active', 'fs-landscape');
        var fsBtn = document.getElementById('btnFullscreen');
        if (fsBtn) fsBtn.innerHTML = ICONS.fullscreen;
        updateTransform();
    }}
}});
document.addEventListener('webkitfullscreenchange', function() {{
    var card = document.getElementById('playerCard');
    if (!document.webkitFullscreenElement && card && card.classList.contains('fs-active')) {{
        card.classList.remove('fs-active', 'fs-landscape');
        var fsBtn = document.getElementById('btnFullscreen');
        if (fsBtn) fsBtn.innerHTML = ICONS.fullscreen;
        updateTransform();
    }}
}});
var fsResizeTimer;
window.addEventListener('resize', function() {{
    clearTimeout(fsResizeTimer);
    fsResizeTimer = setTimeout(function() {{
        var card = document.getElementById('playerCard');
        if (!card || !card.classList.contains('fs-active')) return;
        var isPortrait = window.innerHeight > window.innerWidth;
        card.classList.toggle('fs-landscape', isPortrait);
        updateTransform();
    }}, 150);
}});

// ===== 键盘快捷键 =====
document.addEventListener('keydown', function(e) {{
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    if (e.code === 'Space') {{ e.preventDefault(); togglePlay(); }}
    if (e.code === 'ArrowRight') {{ video.currentTime = Math.min(video.duration || 0, video.currentTime + 5); showControls(); }}
    if (e.code === 'ArrowLeft') {{ video.currentTime = Math.max(0, video.currentTime - 5); showControls(); }}
    if (e.code === 'ArrowUp') {{ e.preventDefault(); video.volume = Math.min(1, video.volume + 0.1); }}
    if (e.code === 'ArrowDown') {{ e.preventDefault(); video.volume = Math.max(0, video.volume - 0.1); }}
    if (e.code === 'KeyF' || e.code === 'Enter') {{ e.preventDefault(); toggleFullscreen(); }}
    if (e.code === 'Escape') {{
        var c = document.getElementById('playerCard');
        if (c && c.classList.contains('fs-active')) exitFullscreen(c);
    }}
}});

// ===== 设置面板 =====
var settingsBtn = document.getElementById('ccSettingsBtn');
var settingsPanel = document.getElementById('ccSettingsPanel');
function showSettingsPanel() {{
    if (settingsPanel) settingsPanel.classList.add('show');
}}
function hideSettingsPanel() {{
    if (settingsPanel) settingsPanel.classList.remove('show');
}}
if (settingsBtn) {{
    settingsBtn.addEventListener('click', function(e) {{
        e.stopPropagation();
        if (settingsPanel && settingsPanel.classList.contains('show')) {{
            hideSettingsPanel();
        }} else {{
            showSettingsPanel();
        }}
        showControls();
    }});
}}
// 点击面板外部关闭
document.addEventListener('click', function(e) {{
    if (settingsPanel && !settingsPanel.contains(e.target) && e.target !== settingsBtn) {{
        hideSettingsPanel();
    }}
}});
// 画面设置项事件
document.querySelectorAll('.cc-settings-item').forEach(function(btn) {{
    btn.addEventListener('click', function(e) {{
        e.stopPropagation();
        var action = btn.getAttribute('data-action');
        if (action === 'rotate-left') rotation = (rotation - 90 + 360) % 360;
        else if (action === 'rotate-right') rotation = (rotation + 90) % 360;
        else if (action === 'flip-h') {{
            flipH = !flipH;
            var bh = document.getElementById('btnFlipH');
            if (bh) bh.classList.toggle('active', flipH);
        }}
        else if (action === 'flip-v') {{
            flipV = !flipV;
            var bv = document.getElementById('btnFlipV');
            if (bv) bv.classList.toggle('active', flipV);
        }}
        else if (action === 'reset') {{
            rotation = 0; flipH = false; flipV = false;
            var bh2 = document.getElementById('btnFlipH');
            var bv2 = document.getElementById('btnFlipV');
            if (bh2) bh2.classList.remove('active');
            if (bv2) bv2.classList.remove('active');
        }}
        updateTransform();
        showControls();
    }});
}});

// ===== 上一个/下一个 =====
document.getElementById('ccPrevBtn').addEventListener('click', function() {{
    var items = document.querySelectorAll('.playlist-item');
    for (var i = 0; i < items.length; i++) {{
        if (items[i].classList.contains('active') && i > 0) {{
            window.location.href = items[i - 1].href;
            break;
        }}
    }}
}});
document.getElementById('ccNextBtn').addEventListener('click', function() {{
    var items = document.querySelectorAll('.playlist-item');
    for (var i = 0; i < items.length; i++) {{
        if (items[i].classList.contains('active') && i + 1 < items.length) {{
            window.location.href = items[i + 1].href;
            break;
        }}
    }}
}});

// ===== 移动端手势：水平滑动快进快退 =====
var origTouchX = 0, origTouchY = 0;
wrapper.addEventListener('touchstart', function(e) {{
    if (e.target.closest('.custom-controls')) return;
    if (e.touches.length !== 1) return;
    var t = e.touches[0];
    touchStartX = t.clientX;
    touchStartY = t.clientY;
    touchStartTime = Date.now();
    touchStartCT = video.currentTime || 0;
    touchMoved = false;
    seekTouchMode = false;
    origTouchX = t.clientX;
    origTouchY = t.clientY;
}}, {{passive: true}});

wrapper.addEventListener('touchmove', function(e) {{
    if (e.target.closest('.custom-controls')) return;
    if (!e.touches || e.touches.length !== 1) return;
    var t = e.touches[0];
    var dx = t.clientX - touchStartX;
    var dy = t.clientY - touchStartY;
    if (!touchMoved) {{
        if (Math.abs(dx) < 12 && Math.abs(dy) < 12) return;
        touchMoved = true;
        seekTouchMode = Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 20;
    }}
    if (seekTouchMode) {{
        e.preventDefault && e.preventDefault();
        var wrapRect = wrapper.getBoundingClientRect();
        var width = wrapRect.width;
        // 每屏幕宽度 = 视频总时长 60%
        var seekRange = (video.duration || 120) * 0.6;
        var delta = (dx / Math.max(1, width)) * seekRange;
        var newT = Math.max(0, Math.min(video.duration || 0, touchStartCT + delta));
        var sign = delta >= 0 ? '+' : '';
        seekTip.textContent = fmtTime(newT) + '  (' + sign + Math.round(delta) + '秒)';
        seekTip.classList.add('show');
        video.currentTime = newT;
        showControls();
    }}
}}, {{passive: false}});

wrapper.addEventListener('touchend', function(e) {{
    if (seekTouchMode) {{
        seekTip.classList.remove('show');
    }}
    touchMoved = false;
    seekTouchMode = false;
}});

// ===== 初始化 =====
showControls();
updatePlayUI();
updateVolumeUI();
// 防止浏览器原生菜单长按
if (isTouch) {{
    wrapper.addEventListener('contextmenu', function(e) {{ e.preventDefault(); }});
}}

// ===== 自动播放下一个（保留原有逻辑） =====
video.addEventListener('ended', function() {{
    var items = document.querySelectorAll('.playlist-item');
    for (var i = 0; i < items.length; i++) {{
        if (items[i].classList.contains('active') && i + 1 < items.length) {{
            window.location.href = items[i + 1].href;
            break;
        }}
    }}
}});

}})();
// 音频独立逻辑
(function() {{
    var audioPlayer = document.getElementById('mediaPlayer');
    if (!audioPlayer || audioPlayer.tagName !== 'AUDIO') return;
    // 键盘快捷键
    document.addEventListener('keydown', function(e) {{
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        if (e.code === 'Space') {{ e.preventDefault(); audioPlayer.paused ? audioPlayer.play() : audioPlayer.pause(); }}
        if (e.code === 'ArrowRight') {{ audioPlayer.currentTime = Math.min(audioPlayer.duration||0, audioPlayer.currentTime + 5); }}
        if (e.code === 'ArrowLeft') {{ audioPlayer.currentTime = Math.max(0, audioPlayer.currentTime - 5); }}
        if (e.code === 'ArrowUp') {{ e.preventDefault(); audioPlayer.volume = Math.min(1, audioPlayer.volume + 0.1); }}
        if (e.code === 'ArrowDown') {{ e.preventDefault(); audioPlayer.volume = Math.max(0, audioPlayer.volume - 0.1); }}
    }});
    // 自动播放下一个
    audioPlayer.addEventListener('ended', function() {{
        var items = document.querySelectorAll('.playlist-item');
        for (var i = 0; i < items.length; i++) {{
            if (items[i].classList.contains('active') && i + 1 < items.length) {{
                window.location.href = items[i + 1].href;
                break;
            }}
        }}
    }});
}})();
</script>
</body>
</html>'''

        html_content = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(html_content)))
        self.end_headers()
        return io.BytesIO(html_content)

    # ==================== 美观的目录列表页面 ====================
    def render_directory_listing(self, path):
        """渲染美观的文件列表页面"""
        try:
            names = os.listdir(path)
        except os.error:
            self.send_error(404, "No permission to list directory")
            return None

        names.sort(key=lambda a: a.lower())

        # 分类：文件夹、视频、音频、其他
        folders = []
        videos = []
        audios = []
        others = []

        for name in names:
            fullname = os.path.join(path, name)
            if os.path.isdir(fullname):
                size = -1
                folders.append((name, size))
            else:
                try:
                    size = os.path.getsize(fullname)
                except Exception:
                    size = 0
                ext = os.path.splitext(name)[1].lower()
                if ext in VIDEO_MIME_TYPES:
                    videos.append((name, size))
                elif ext in AUDIO_MIME_TYPES:
                    audios.append((name, size))
                else:
                    others.append((name, size))

        total_media = len(videos) + len(audios)
        display_path = self.path if self.path else '/'

        html_parts = [
            '<!DOCTYPE html>',
            '<html lang="zh-CN"><head>',
            '<meta charset="UTF-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
            f'<title>AryPlayer - 视频播放器</title>',
            '<style>',
            ':root{',
            '  --primary:#4A90E2;',
            '  --primary-hover:#357ABD;',
            '  --bg:#FAFAFA;',
            '  --card:#FFFFFF;',
            '  --text-main:#1F2937;',
            '  --text-sub:#6B7280;',
            '  --text-light:#9CA3AF;',
            '  --border:#E5E7EB;',
            '  --border-light:#F3F4F6;',
            '  --shadow-sm:0 1px 2px rgba(0,0,0,0.04);',
            '  --shadow:0 4px 16px rgba(0,0,0,0.06);',
            '  --shadow-lg:0 8px 32px rgba(0,0,0,0.10);',
            '  --radius:14px;',
            '  --radius-sm:10px;',
            '}',
            '*{margin:0;padding:0;box-sizing:border-box;}',
            'body{',
            '  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;',
            '  background:var(--bg);',
            '  color:var(--text-main);',
            '  min-height:100vh;',
            '  -webkit-font-smoothing:antialiased;',
            '}',
            '.topbar{',
            '  background:var(--card);',
            '  border-bottom:1px solid var(--border-light);',
            '  position:sticky;top:0;z-index:100;',
            '  box-shadow:var(--shadow-sm);',
            '}',
            '.topbar-inner{',
            '  max-width:1100px;margin:0 auto;padding:16px 28px;',
            '  display:flex;align-items:center;gap:16px;',
            '}',
            '.logo{display:flex;align-items:center;gap:10px;font-weight:700;font-size:19px;color:var(--primary);}',
            '.logo-icon{',
            '  width:38px;height:38px;',
            '  background:linear-gradient(135deg,var(--primary),#6BA8EA);',
            '  border-radius:11px;',
            '  display:flex;align-items:center;justify-content:center;color:#fff;font-size:19px;',
            '  box-shadow:0 3px 10px rgba(74,144,226,0.28);',
            '}',
            '.main{max-width:1100px;margin:0 auto;padding:28px;}',
            '.hero{',
            '  background:linear-gradient(135deg,#ffffff 0%,#f0f7ff 100%);',
            '  border-radius:var(--radius);',
            '  padding:28px 32px;',
            '  margin-bottom:24px;',
            '  border:1px solid rgba(74,144,226,0.12);',
            '  box-shadow:var(--shadow-sm);',
            '}',
            '.hero-top{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:16px;margin-bottom:16px;}',
            '.hero-title{font-size:22px;font-weight:600;color:var(--text-main);display:flex;align-items:center;gap:10px;}',
            '.hero-path{font-size:14px;color:var(--text-sub);word-break:break-all;}',
            '.stats{display:flex;gap:12px;flex-wrap:wrap;}',
            '.stat-badge{',
            '  display:inline-flex;align-items:center;gap:6px;',
            '  padding:7px 14px;border-radius:20px;',
            '  font-size:13px;font-weight:500;',
            '}',
            '.stat-folder{background:#FFF8E1;color:#B8860B;}',
            '.stat-video{background:#E8F0FE;color:var(--primary);}',
            '.stat-audio{background:#E6F4EA;color:#2E8B57;}',
            '.stat-other{background:#F3F4F6;color:var(--text-sub);}',
            '.back-link{',
            '  display:inline-flex;align-items:center;gap:7px;',
            '  padding:9px 17px;border:1px solid var(--border);border-radius:var(--radius-sm);',
            '  background:var(--card);color:var(--text-sub);',
            '  text-decoration:none;font-size:14px;font-weight:500;',
            '  transition:all 0.2s ease;',
            '}',
            '.back-link:hover{background:var(--border-light);color:var(--primary);border-color:var(--primary);}',
            '.section{margin-bottom:26px;}',
            '.section-title{',
            '  font-size:15px;font-weight:600;color:var(--text-main);',
            '  margin-bottom:12px;display:flex;align-items:center;gap:8px;',
            '}',
            '.section-title .count{font-size:13px;color:var(--text-light);font-weight:400;}',
            '.grid{',
            '  display:grid;gap:12px;',
            '  grid-template-columns:repeat(auto-fill,minmax(320px,1fr));',
            '}',
            '@media(max-width:600px){.grid{grid-template-columns:1fr;}}',
            '.card{',
            '  background:var(--card);border-radius:var(--radius-sm);',
            '  padding:16px;display:flex;align-items:center;gap:14px;',
            '  text-decoration:none;',
            '  border:1px solid var(--border-light);',
            '  transition:all 0.2s ease;',
            '  box-shadow:var(--shadow-sm);',
            '}',
            '.card:hover{',
            '  transform:translateY(-2px);',
            '  box-shadow:var(--shadow);',
            '  border-color:rgba(74,144,226,0.2);',
            '}',
            '.card-icon{',
            '  width:48px;height:48px;border-radius:12px;',
            '  display:flex;align-items:center;justify-content:center;',
            '  font-size:22px;flex-shrink:0;',
            '}',
            '.icon-folder{background:linear-gradient(135deg,#FFE58F,#FFD666);color:#AD6800;}',
            '.icon-video{background:linear-gradient(135deg,#A7CBFF,var(--primary));color:#fff;}',
            '.icon-audio{background:linear-gradient(135deg,#95DEAA,#52C41A);color:#fff;}',
            '.icon-file{background:linear-gradient(135deg,#D9D9D9,#BFBFBF);color:#fff;}',
            '.card-body{flex:1;min-width:0;}',
            '.card-name{',
            '  font-size:15px;font-weight:500;color:var(--text-main);',
            '  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;',
            '  margin-bottom:5px;',
            '}',
            '.card-meta{font-size:13px;color:var(--text-light);display:flex;align-items:center;gap:8px;}',
            '.card-action{',
            '  opacity:0;transition:opacity 0.2s ease;',
            '  padding:7px 12px;border-radius:8px;',
            '  background:var(--primary);color:#fff;',
            '  font-size:13px;font-weight:500;',
            '  flex-shrink:0;',
            '}',
            '.card:hover .card-action{opacity:1;}',
            '.empty{',
            '  padding:60px 20px;text-align:center;',
            '}',
            '.empty-icon{font-size:48px;margin-bottom:16px;opacity:0.5;}',
            '.empty-text{font-size:15px;color:var(--text-light);}',
            '.footer{',
            '  max-width:1100px;margin:0 auto;padding:24px 28px 40px;',
            '  text-align:center;font-size:13px;color:var(--text-light);',
            '}',
            '</style>',
            '</head><body>',
            '<header class="topbar"><div class="topbar-inner">',
            '<div class="logo"><div class="logo-icon">▶</div>AryPlayer</div>',
            '</div></header>',
            '<main class="main">',
            '<section class="hero">',
            '<div class="hero-top">',
            '<div>',
            f'<div class="hero-title">📁 媒体库</div>',
            f'<div class="hero-path">{display_path}</div>',
            '</div>',
            '<div class="stats">',
            f'<span class="stat-badge stat-folder">📂 {len(folders)} 个文件夹</span>',
            f'<span class="stat-badge stat-video">🎬 {len(videos)} 个视频</span>',
            f'<span class="stat-badge stat-audio">🎵 {len(audios)} 个音频</span>',
            (f'<span class="stat-badge stat-other">📄 {len(others)} 个文件</span>' if others else ''),
            '</div>',
            '</div>',
        ]

        # 返回上级目录
        if self.path != '/':
            parent = os.path.dirname(self.path.rstrip('/'))
            if not parent:
                parent = '/'
            html_parts.append(f'<a class="back-link" href="{parent}/">← 返回上级目录</a>')

        html_parts.append('</section>')

        # 文件夹区域
        if folders:
            html_parts.append('<section class="section">')
            html_parts.append(f'<div class="section-title">📂 文件夹 <span class="count">({len(folders)})</span></div>')
            html_parts.append('<div class="grid">')
            for name, _ in folders:
                linkname = name + "/"
                safe_link = urllib.parse.quote(linkname)
                html_parts.append(
                    f'<a class="card" href="{safe_link}">'
                    f'<div class="card-icon icon-folder">📂</div>'
                    f'<div class="card-body">'
                    f'<div class="card-name">{name}</div>'
                    f'<div class="card-meta">文件夹</div>'
                    f'</div>'
                    f'<div class="card-action">打开 →</div>'
                    f'</a>'
                )
            html_parts.append('</div></section>')

        # 视频区域
        if videos:
            html_parts.append('<section class="section">')
            html_parts.append(f'<div class="section-title">🎬 视频文件 <span class="count">({len(videos)})</span></div>')
            html_parts.append('<div class="grid">')
            for name, size in videos:
                safe_link = urllib.parse.quote(name)
                html_parts.append(
                    f'<a class="card" href="{safe_link}?play=1">'
                    f'<div class="card-icon icon-video">🎬</div>'
                    f'<div class="card-body">'
                    f'<div class="card-name">{name}</div>'
                    f'<div class="card-meta">{format_file_size(size)} · {os.path.splitext(name)[1].upper()[1:]}</div>'
                    f'</div>'
                    f'<div class="card-action">播放 ▶</div>'
                    f'</a>'
                )
            html_parts.append('</div></section>')

        # 音频区域
        if audios:
            html_parts.append('<section class="section">')
            html_parts.append(f'<div class="section-title">🎵 音频文件 <span class="count">({len(audios)})</span></div>')
            html_parts.append('<div class="grid">')
            for name, size in audios:
                safe_link = urllib.parse.quote(name)
                html_parts.append(
                    f'<a class="card" href="{safe_link}?play=1">'
                    f'<div class="card-icon icon-audio">🎵</div>'
                    f'<div class="card-body">'
                    f'<div class="card-name">{name}</div>'
                    f'<div class="card-meta">{format_file_size(size)} · {os.path.splitext(name)[1].upper()[1:]}</div>'
                    f'</div>'
                    f'<div class="card-action">播放 ▶</div>'
                    f'</a>'
                )
            html_parts.append('</div></section>')

        # 其他文件区域
        if others:
            html_parts.append('<section class="section">')
            html_parts.append(f'<div class="section-title">📄 其他文件 <span class="count">({len(others)})</span></div>')
            html_parts.append('<div class="grid">')
            for name, size in others:
                safe_link = urllib.parse.quote(name)
                html_parts.append(
                    f'<a class="card" href="{safe_link}">'
                    f'<div class="card-icon icon-file">📄</div>'
                    f'<div class="card-body">'
                    f'<div class="card-name">{name}</div>'
                    f'<div class="card-meta">{format_file_size(size)} · {os.path.splitext(name)[1].upper()[1:] or "未知"}</div>'
                    f'</div>'
                    f'<div class="card-action">下载 ↓</div>'
                    f'</a>'
                )
            html_parts.append('</div></section>')

        # 空状态
        if not folders and not videos and not audios and not others:
            html_parts.append(
                '<section class="empty">'
                '<div class="empty-icon">📭</div>'
                '<div class="empty-text">该目录下暂无文件</div>'
                '</section>'
            )

        html_parts.append('</main>')
        html_parts.append('<footer class="footer">AryPlayer · 高性能视频流媒体服务器</footer>')
        html_parts.append('</body></html>')

        html_content = ''.join(html_parts).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(html_content)))
        self.end_headers()

        return io.BytesIO(html_content)

    def log_message(self, format, *args):
        import datetime
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {args[0]}")


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """多线程 HTTP 服务器"""
    allow_reuse_address = True
    daemon_threads = True


def get_local_ip():
    """获取本机局域网 IP"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def main():
    parser = argparse.ArgumentParser(
        description='AryPlayer - 美观的视频流 HTTP 服务器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python app.py                              # 默认配置启动
  python app.py -p 8080                      # 自定义端口
  python app.py -d D:/Videos                 # 指定视频目录
  python app.py -b 0.0.0.0:8080              # 绑定所有网卡
        """
    )
    parser.add_argument('-p', '--port', type=int, default=9000,
                        help='监听端口 (默认: 9000)')
    parser.add_argument('-b', '--bind', default='',
                        help='绑定地址 (默认: 所有网卡)')
    parser.add_argument('-d', '--directory', default=os.getcwd(),
                        help='服务目录 (默认: 当前目录)')

    args = parser.parse_args()

    # 切换工作目录
    os.chdir(args.directory)

    bind_addr = args.bind if args.bind else ''

    try:
        server = ThreadedHTTPServer((bind_addr, args.port), VideoRequestHandler)

        local_ip = get_local_ip()

        print("=" * 62)
        print("  AryPlayer 高性能视频流服务器已启动")
        print("=" * 62)
        print(f"  📁 服务目录: {args.directory}")
        print(f"  🌐 本地访问: http://localhost:{args.port}")
        print(f"  📱 手机访问: http://{local_ip}:{args.port}")
        print(f"  ✨ 内置美观播放器 · 分类浏览 · 连续播放")
        print(f"  ⚙️  Range请求 | 多线程 | 64KB缓冲区优化")
        print(f"  🎯 支持格式: MP4/MKV/AVI/MOV/MP3/FLAC 等")
        print("=" * 62)
        print("  提示: 点击视频/音频文件即可进入美观播放器页面")
        print("  快捷键: 空格(播放/暂停) ←→(±5s) ↑↓(音量)")
        print("  按 Ctrl+C 停止服务器")
        print("=" * 62)

        server.serve_forever()

    except KeyboardInterrupt:
        print("\n\n  🛑 服务器已停止")
        server.server_close()
        sys.exit(0)
    except PermissionError:
        print(f"  ❌ 错误: 端口 {args.port} 已被占用，请使用 -p 参数指定其他端口")
        sys.exit(1)
    except Exception as e:
        print(f"  ❌ 错误: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
