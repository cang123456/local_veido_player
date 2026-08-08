# -*- coding: utf-8 -*-
"""
高性能视频流 HTTP 服务器
支持 Range 请求（断点续传）、多线程、优化的缓冲区
解决 Python 内置 http.server 视频播放卡顿问题

使用方法:
    python video_server.py                    # 默认端口 9000
    python video_server.py -p 8080            # 指定端口
    python video_server.py -d D:/Videos       # 指定目录
    python video_server.py -b 0.0.0.0         # 指定绑定地址
"""

import os
import sys
import io
import argparse
import mimetypes
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


class VideoRequestHandler(SimpleHTTPRequestHandler):
    """增强的请求处理器，支持 Range 请求和优化的响应头"""
    
    # 设置正确的 MIME 类型
    def guess_type(self, path):
        ext = os.path.splitext(path)[1].lower()
        if ext in VIDEO_MIME_TYPES:
            return VIDEO_MIME_TYPES[ext]
        if ext in AUDIO_MIME_TYPES:
            return AUDIO_MIME_TYPES[ext]
        mime_type, _ = mimetypes.guess_type(path)
        return mime_type or 'application/octet-stream'
    
    # 发送文件 - 支持 Range 请求
    def send_head(self):
        path = self.translate_path(self.path)
        
        if os.path.isdir(path):
            return SimpleHTTPRequestHandler.send_head(self)
        
        if not os.path.exists(path):
            self.send_error(404, "File not found")
            return None
        
        try:
            file_size = os.path.getsize(path)
            mime_type = self.guess_type(path)
            
            # 处理 Range 请求
            range_header = self.headers.get('Range')
            
            if range_header:
                # 解析 Range: bytes=start-end
                range_match = range_header.strip().replace('bytes=', '')
                start, end = None, None
                
                if '-' in range_match:
                    parts = range_match.split('-', 1)
                    start = int(parts[0]) if parts[0] else None
                    end = int(parts[1]) if parts[1] else None
                
                # 验证并调整范围
                if start is not None and start >= file_size:
                    # 范围超出文件大小
                    self.send_response(416)
                    self.send_header('Content-Range', f'bytes */{file_size}')
                    self.end_headers()
                    return None
                
                if start is None:
                    # Suffix range: bytes=-500 (最后500字节)
                    start = max(0, file_size - (end or 0))
                    end = file_size - 1
                elif end is None or end >= file_size:
                    end = file_size - 1
                
                length = end - start + 1
                
                # 发送 206 Partial Content
                self.send_response(206)
                self.send_header('Content-Type', mime_type)
                self.send_header('Content-Length', str(length))
                self.send_header('Content-Range', f'bytes {start}-{end}/{file_size}')
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Cache-Control', 'public, max-age=3600')
                self.end_headers()
                
                # 打开文件并定位到指定位置
                f = open(path, 'rb')
                f.seek(start)
                return f
            
            else:
                # 普通请求 - 发送完整文件
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
    
    # 重写 copyfile 使用更大的缓冲区
    def copyfile(self, source, outputfile):
        try:
            while True:
                buf = source.read(BUFFER_SIZE)
                if not buf:
                    break
                outputfile.write(buf)
        except ConnectionResetError:
            pass  # 客户端断开连接时忽略
    
    # 完整重写 do_GET 方法
    def do_GET(self):
        f = None
        try:
            f = self.send_head()
            if f:
                self.copyfile(f, self.wfile)
        except ConnectionResetError:
            pass  # 客户端断开连接时忽略
        finally:
            if f:
                try:
                    f.close()
                except Exception:
                    pass
    
    # 提供更好的目录列表
    def list_directory(self, path):
        try:
            names = os.listdir(path)
        except os.error:
            self.send_error(404, "No permission to list directory")
            return None
        
        names.sort(key=lambda a: a.lower())
        
        # HTML 模板 - 美化目录列表
        html_parts = [
            '<!DOCTYPE html>',
            '<html><head><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            '<title>视频服务器</title>',
            '<style>',
            'body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;margin:20px;background:#f5f5f5;}',
            'h1{color:#333;margin-bottom:20px;}',
            '.container{max-width:800px;margin:0 auto;background:#fff;padding:20px;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,0.1);}',
            '.file-list{list-style:none;padding:0;}',
            '.file-item{padding:12px;border-bottom:1px solid #eee;display:flex;align-items:center;justify-content:space-between;}',
            '.file-item:last-child{border-bottom:none;}',
            '.file-item a{text-decoration:none;color:#1976d2;font-size:16px;}',
            '.file-item a:hover{text-decoration:underline;}',
            '.file-size{color:#999;font-size:14px;}',
            '.icon{margin-right:8px;}',
            '.folder-item{background:#fffde7;}',
            '.video-item{background:#e3f2fd;}',
            '.audio-item{background:#e8f5e9;}',
            '.back-link{display:inline-block;margin-bottom:15px;color:#666;text-decoration:none;}',
            '.back-link:hover{color:#333;}',
            '</style>',
            '</head><body>',
            '<div class="container">',
            f'<h1>📁 {self.path}</h1>',
        ]
        
        # 返回上级目录
        if self.path != '/':
            parent = os.path.dirname(self.path.rstrip('/'))
            html_parts.append(f'<a class="back-link" href="{parent}/">⬅ 返回上级</a>')
        
        html_parts.append('<ul class="file-list">')
        
        for name in names:
            fullname = os.path.join(path, name)
            displayname = linkname = name
            
            if os.path.isdir(fullname):
                displayname = name + "/"
                linkname = name + "/"
                size_str = "📁 目录"
                item_class = "folder-item"
                icon = "📂"
            else:
                size = os.path.getsize(fullname)
                size_str = self.format_file_size(size)
                ext = os.path.splitext(name)[1].lower()
                if ext in VIDEO_MIME_TYPES:
                    item_class = "video-item"
                    icon = "🎬"
                elif ext in AUDIO_MIME_TYPES:
                    item_class = "audio-item"
                    icon = "🎵"
                else:
                    item_class = ""
                    icon = "📄"
            
            html_parts.append(
                f'<li class="file-item {item_class}">'
                f'<a href="{linkname}">{icon} {displayname}</a>'
                f'<span class="file-size">{size_str}</span>'
                f'</li>'
            )
        
        html_parts.append('</ul></div></body></html>')
        
        html_content = ''.join(html_parts).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(html_content)))
        self.end_headers()
        
        return io.BytesIO(html_content)
    
    @staticmethod
    def format_file_size(size):
        """格式化文件大小"""
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.1f} GB"
    
    # 日志格式优化
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
    except:
        return '127.0.0.1'


def main():
    parser = argparse.ArgumentParser(
        description='高性能视频流 HTTP 服务器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python video_server.py                    # 默认配置启动
  python video_server.py -p 8080            # 自定义端口
  python video_server.py -d D:/Videos       # 指定视频目录
  python video_server.py -b 0.0.0.0:8080    # 绑定所有网卡
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
    
    # 确定绑定地址
    bind_addr = args.bind if args.bind else ''
    
    try:
        server = ThreadedHTTPServer((bind_addr, args.port), VideoRequestHandler)
        
        local_ip = get_local_ip()
        
        print("=" * 60)
        print("🎬 高性能视频流服务器已启动")
        print("=" * 60)
        print(f"📁 服务目录: {args.directory}")
        print(f"🌐 本地访问: http://localhost:{args.port}")
        print(f"📱 手机访问: http://{local_ip}:{args.port}")
        print(f"⚙️  功能特性: Range请求 | 多线程 | 64KB缓冲区")
        print(f"🎯 支持格式: MP4/MKV/AVI/MOV/FLV/WebM 等")
        print("=" * 60)
        print("提示: 确保手机和电脑在同一WiFi网络下")
        print("按 Ctrl+C 停止服务器")
        print("=" * 60)
        
        server.serve_forever()
        
    except KeyboardInterrupt:
        print("\n\n🛑 服务器已停止")
        server.server_close()
        sys.exit(0)
    except PermissionError:
        print(f"❌ 错误: 端口 {args.port} 已被占用，请使用 -p 参数指定其他端口")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 错误: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
