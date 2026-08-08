module.exports = {
  apps: [{
    name: 'my_python_app',                    // 应用名称
    cwd: 'E:/OBS_vedio/vedio',                // 工作目录（项目根目录）
    script: 'app-v2.py',                         // 入口脚本
    interpreter: 'python',                   // Python解释器
    out_file: 'D:/logs/out.log',             // 标准输出日志
    error_file: 'D:/logs/error.log',         // 错误日志
    autorestart: true,                        // 崩溃自动重启
    watch: false,                             // 不监听文件变化
    env: {
      PYTHONIOENCODING: 'utf-8',             // 强制使用UTF-8编码，解决Emoji乱码
      PYTHONUTF8: '1'                        // 启用Python UTF-8模式
    }
  }]
}