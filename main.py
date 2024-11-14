import sys
import os
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                              QHBoxLayout, QLineEdit, QPushButton, QLabel, QProgressBar,
                              QFileDialog, QTimeEdit, QFrame, QMessageBox, QSizePolicy,
                              QScrollArea)
from PySide6.QtCore import QThread, Signal, Qt, QTime
from bilibili_api import video, sync
import requests
import subprocess
from moviepy.editor import VideoFileClip, AudioFileClip, concatenate_audioclips, AudioClip
import asyncio
class DownloadWorker(QThread):
    progress_signal = Signal(str)
    progress_value = Signal(int)
    finished_signal = Signal(str)

    def __init__(self, url, download_type='mp3'):
        super().__init__()
        self.url = url
        self.download_type = download_type

    def _download_stream(self, response, save_path):
        """下载单个流文件"""
        total_size = int(response.headers.get('content-length', 0))
        block_size = 1024
        downloaded = 0
        
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=block_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        progress = int((downloaded / total_size) * 100)
                        self.progress_value.emit(progress)

    def _merge_audio_video(self, video_path, audio_path, output_path):
        try:
            # 使用 moviepy 合并音视频
            video_clip = VideoFileClip(video_path)
            audio_clip = AudioFileClip(audio_path)
            final_clip = video_clip.set_audio(audio_clip)
            
            final_clip.write_videofile(output_path, 
                                     codec='libx264',
                                     audio_codec='aac',
                                     temp_audiofile='temp-audio.m4a',
                                     remove_temp=True)
            
            # 清理资源
            video_clip.close()
            audio_clip.close()
            final_clip.close()
            
            return True
        except Exception as e:
            self.progress_signal.emit(f"合并失败: {str(e)}")
            return False

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.download_media())
        except Exception as e:
            self.finished_signal.emit(f"下载失败: {str(e)}")
        finally:
            loop.close()

    async def download_media(self):
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://www.bilibili.com'
            }

            if 'BV' in self.url:
                bv_number = 'BV' + self.url.split('BV')[1][:10]
            else:
                raise ValueError("链接中未找到BV号")
            
            v = video.Video(bvid=bv_number)
            video_info = await v.get_info()
            title = video_info['title']
            cid = video_info['cid']
            
            # 创建下载目录
            if getattr(sys, 'frozen', False):
                current_dir = os.path.dirname(sys.executable)
            else:
                current_dir = os.path.dirname(os.path.abspath(__file__))
            
            download_dir = os.path.join(current_dir, 'downloads')
            os.makedirs(download_dir, exist_ok=True)

            # 获取下载信息
            download_info = await v.get_download_url(cid=cid)
            
            if self.download_type == 'mp3':
                # 下载音频为MP3
                audio_url = download_info['dash']['audio'][0]['baseUrl']
                output_path = os.path.join(download_dir, f'{title}.mp3')
                
                self.progress_signal.emit(f"正在下载音频: {title}")
                audio_response = requests.get(audio_url, headers=headers, stream=True)
                self._download_stream(audio_response, output_path)
                self.finished_signal.emit(f"下载完成: {output_path}")
                
            elif self.download_type == 'mp4audio':
                # 下载音频为MP4格式
                audio_url = download_info['dash']['audio'][0]['baseUrl']
                temp_audio = os.path.join(download_dir, f'temp_audio_{title}.m4a')
                output_path = os.path.join(download_dir, f'{title}_audio.mp4')
                
                self.progress_signal.emit(f"正在下载音频: {title}")
                audio_response = requests.get(audio_url, headers=headers, stream=True)
                self._download_stream(audio_response, temp_audio)
                
                try:
                    # 使用 moviepy 转换为 MP4 格式
                    audio = AudioFileClip(temp_audio)
                    audio.write_audiofile(output_path, codec='aac')
                    audio.close()
                    
                    # 清理时文件
                    try:
                        os.remove(temp_audio)
                    except:
                        pass
                    
                    self.finished_signal.emit(f"下载完成: {output_path}")
                except Exception as e:
                    self.finished_signal.emit(f"音频转换失败: {str(e)}")
                
            elif self.download_type == 'mp4':
                # 只下载视频流
                video_url = download_info['dash']['video'][0]['baseUrl']
                output_path = os.path.join(download_dir, f'{title}.mp4')
                
                self.progress_signal.emit(f"正在下载视频: {title}")
                video_response = requests.get(video_url, headers=headers, stream=True)
                self._download_stream(video_response, output_path)
                self.finished_signal.emit(f"下载完成: {output_path}")
                
            elif self.download_type == 'full_mp4':
                # 下载视频和音频并合并
                video_url = download_info['dash']['video'][0]['baseUrl']
                audio_url = download_info['dash']['audio'][0]['baseUrl']
                
                temp_video = os.path.join(download_dir, f'temp_video_{title}.mp4')
                temp_audio = os.path.join(download_dir, f'temp_audio_{title}.m4a')
                final_path = os.path.join(download_dir, f'{title}.mp4')

                # 下载视频流
                self.progress_signal.emit(f"正在下载视频流: {title}")
                video_response = requests.get(video_url, headers=headers, stream=True)
                self._download_stream(video_response, temp_video)
                
                # 下载音频流
                self.progress_signal.emit(f"正在下载音频流: {title}")
                audio_response = requests.get(audio_url, headers=headers, stream=True)
                self._download_stream(audio_response, temp_audio)

                # 合并音视频
                self.progress_signal.emit("正在合并音视频...")
                if self._merge_audio_video(temp_video, temp_audio, final_path):
                    # 清理临时文件
                    try:
                        os.remove(temp_video)
                        os.remove(temp_audio)
                    except:
                        pass
                    self.finished_signal.emit(f"下载完成: {final_path}")
                else:
                    self.finished_signal.emit("合并失败")

        except Exception as e:
            self.finished_signal.emit(f"下载失败: {str(e)}")

class ClipWorker(QThread):
    progress_signal = Signal(str)
    finished_signal = Signal(str)

    def __init__(self, file_path, start_time, end_time, save_audio_only=False, video_only=False):
        super().__init__()
        self.file_path = file_path
        self.start_time = start_time
        self.end_time = end_time
        self.save_audio_only = save_audio_only
        self.video_only = video_only
        self.media = None
        self.clip = None
        self.save_as_mp4_audio = False

    def format_time(self, seconds):
        """将秒数转换为 HH-mm-ss 格式"""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02d}-{minutes:02d}-{secs:02d}"

    def has_video_stream(self, file_path):
        """检查文件是否包含视频流和音频流"""
        try:
            # 先尝试作为音频文件打开
            try:
                audio = AudioFileClip(file_path)
                has_audio = True
                audio.close()
            except:
                has_audio = False

            # 再尝试作为频文件打开
            try:
                video = VideoFileClip(file_path)
                has_video = video.size[0] > 0 and video.size[1] > 0
                # 如果之前没检测到音频，再次检查视频文件的音频
                if not has_audio:
                    has_audio = video.audio is not None
                video.close()
            except:
                has_video = False

            return has_video, has_audio
        except Exception as e:
            print(f"检查文件流时出错: {str(e)}")
            return False, False

    def run(self):
        try:
            self.progress_signal.emit("开始剪辑...")
            
            # 获取原文件扩展名
            original_ext = os.path.splitext(self.file_path)[1].lower()
            time_range = f"{self.format_time(self.start_time)}_{self.format_time(self.end_time)}"
            base_name = os.path.splitext(self.file_path)[0]
            
            if not self.save_audio_only and original_ext == '.mp4':
                # 处理视频
                self.media = VideoFileClip(self.file_path)
                self.clip = self.media.subclip(self.start_time, self.end_time)
                
                if self.video_only:
                    # 只保视频
                    self.clip = self.clip.without_audio()
                
                output_path = f"{base_name}_剪辑_{time_range}.mp4"
                self.clip.write_videofile(output_path,
                                        codec='libx264',
                                        audio_codec='aac' if not self.video_only else None,
                                        temp_audiofile='temp-audio.m4a',
                                        remove_temp=True)
                
            else:
                # 处理音频
                try:
                    # 直接使用 AudioFileClip 处理，不管是 MP3 还是 MP4
                    self.media = AudioFileClip(self.file_path)
                    self.clip = self.media.subclip(self.start_time, self.end_time)
                    
                    # 根据设置决定输出格式
                    if self.save_as_mp4_audio:
                        output_path = f"{base_name}_剪辑_{time_range}.mp4"
                        self.clip.write_audiofile(output_path, codec='aac')
                    else:
                        output_path = f"{base_name}_剪辑_{time_range}.mp3"
                        self.clip.write_audiofile(output_path,
                                                codec='libmp3lame',
                                                bitrate='192k')
                                            
                except Exception as e:
                    self.progress_signal.emit(f"处理音频时出错: {str(e)}")
                    raise
            
            # 清理资源
            try:
                if hasattr(self, 'clip') and self.clip:
                    self.clip.close()
                if hasattr(self, 'media') and self.media:
                    self.media.close()
            except:
                pass
            
            self.finished_signal.emit(f"剪辑完成: {output_path}")
            
        except Exception as e:
            self.finished_signal.emit(f"剪辑失败: {str(e)}")
            # 确保资源被清理
            try:
                if hasattr(self, 'clip') and self.clip:
                    self.clip.close()
                if hasattr(self, 'media') and self.media:
                    self.media.close()
            except:
                pass

class ConcatWorker(QThread):
    progress_signal = Signal(str)
    finished_signal = Signal(str)
    format_select_signal = Signal()  # 新增信号用于请求格式选择
    
    def __init__(self, file1, file2, start1, end1, start2, end2, concat_type):
        super().__init__()
        self.file1 = file1
        self.file2 = file2
        self.start1 = start1
        self.end1 = end1
        self.start2 = start2
        self.end2 = end2
        self.concat_type = concat_type  # 使用 concat_type 来确定拼接类型和输出格式

    def format_time(self, seconds):
        """将秒数转换为 HH-mm-ss 格式"""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02d}-{minutes:02d}-{secs:02d}"

    def check_file(self, file_path):
        """检查文件的音视频流情况"""
        has_video = False
        has_audio = False
        try:
            # 检查音频
            try:
                audio = AudioFileClip(file_path)
                has_audio = True
                audio.close()
            except:
                pass
            
            # 检查视频
            try:
                video = VideoFileClip(file_path)
                has_video = video.size[0] > 0 and video.size[1] > 0
                if not has_audio:
                    has_audio = video.audio is not None
                video.close()
            except:
                pass
            
            return has_video, has_audio
        except Exception as e:
            self.progress_signal.emit(f"检查文件失败: {str(e)}")
            return False, False

    def check_files(self):
        """检查两个文件的音视频流情况"""
        file1_has_video, file1_has_audio = self.check_file(self.file1)
        file2_has_video, file2_has_audio = self.check_file(self.file2)
        
        # 根据拼接类型返回相应的检查结果
        if 'video' in self.concat_type:
            # 视频拼接模式需要两个文件都有视频流
            return file1_has_video and file2_has_video
        else:
            # 音频拼接模式需要两个文件都有音频流
            return file1_has_audio and file2_has_audio

    def run(self):
        try:
            self.progress_signal.emit("开始拼接...")
            
            # 检查文件是否满足拼接条件
            if not self.check_files():
                if 'video' in self.concat_type:
                    raise ValueError("视频拼接模式需要两个包含视频流的MP4文件")
                else:
                    raise ValueError("音频拼接模式需要两个包含音频流的文件")
            
            # 视频拼接模式
            if self.concat_type == 'video':
                # 加载视频
                video1 = VideoFileClip(self.file1).subclip(self.start1, self.end1)
                video2 = VideoFileClip(self.file2).subclip(self.start2, self.end2)
                
                # 拼接视频
                from moviepy.editor import concatenate_videoclips
                final_clip = concatenate_videoclips([video1, video2])
                
                # 生成输出文件名
                time_range = f"{self.format_time(self.start1)}_{self.format_time(self.end2)}"
                output_path = os.path.join(os.path.dirname(self.file1), f"拼接_{time_range}.mp4")
                
                # 写入文件
                final_clip.write_videofile(output_path,
                                         codec='libx264',
                                         audio_codec='aac',
                                         temp_audiofile='temp-audio.m4a',
                                         remove_temp=True)
                
                # 清理资源
                video1.close()
                video2.close()
                final_clip.close()
                
                self.finished_signal.emit(f"拼接完成: {output_path}")
                
            # 纯视频拼接模式（无音频）
            elif self.concat_type == 'video_only':
                # 加载视频并移除音频
                video1 = VideoFileClip(self.file1).subclip(self.start1, self.end1).without_audio()
                video2 = VideoFileClip(self.file2).subclip(self.start2, self.end2).without_audio()
                
                # 拼接视频
                from moviepy.editor import concatenate_videoclips
                final_clip = concatenate_videoclips([video1, video2])
                
                # 生成输出文件名
                time_range = f"{self.format_time(self.start1)}_{self.format_time(self.end2)}"
                output_path = os.path.join(os.path.dirname(self.file1), f"拼接_{time_range}.mp4")
                
                # 写入文件（不包含音频）
                final_clip.write_videofile(output_path,
                                         codec='libx264',
                                         audio=False)

                # 清理资源
                video1.close()
                video2.close()
                final_clip.close()
                
                self.finished_signal.emit(f"拼接完成: {output_path}")
                
            # 音频拼接模式
            elif 'audio' in self.concat_type:
                clips = []
                
                # 处理第一个文件
                try:
                    # 直接使用 AudioFileClip 处理
                    audio1 = AudioFileClip(self.file1)
                    clip1 = audio1.subclip(self.start1, self.end1)
                    clips.append(clip1)
                except Exception as e:
                    self.progress_signal.emit(f"处理第一个文件时出错: {str(e)}")
                    return
                
                # 处理第二个文件
                try:
                    # 直接使用 AudioFileClip 处理
                    audio2 = AudioFileClip(self.file2)
                    clip2 = audio2.subclip(self.start2, self.end2)
                    clips.append(clip2)
                except Exception as e:
                    self.progress_signal.emit(f"处理第二个文件时出错: {str(e)}")
                    return
                
                try:
                    # 拼接音频
                    final_clip = concatenate_audioclips(clips)
                    
                    # 生成输出文件名
                    time_range = f"{self.format_time(self.start1)}_{self.format_time(self.end2)}"
                    output_ext = '.mp3' if self.concat_type == 'audio_mp3' else '.mp4'
                    output_path = os.path.join(os.path.dirname(self.file1), f"拼接_{time_range}{output_ext}")
                    
                    # 保存文件
                    if output_ext == '.mp3':
                        final_clip.write_audiofile(output_path,
                                                 codec='libmp3lame',
                                                 bitrate='192k')
                    else:  # .mp4
                        final_clip.write_audiofile(output_path,
                                                 codec='aac')
                    
                    self.finished_signal.emit(f"拼接完成: {output_path}")
                    
                except Exception as e:
                    self.finished_signal.emit(f"拼接失败: {str(e)}")
                finally:
                    # 清理资源
                    try:
                        for clip in clips:
                            clip.close()
                        if 'final_clip' in locals():
                            final_clip.close()
                    except:
                        pass
            
        except Exception as e:
            self.finished_signal.emit(f"拼接失败: {str(e)}")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("B站视频下载器")
        self.setMinimumSize(800, 600)
        self.resize(800, 700)
        
        # 初始化所有控件
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("请输入B站视频链接...")
        
        # 下载按钮
        self.download_mp3_btn = QPushButton("下载MP3音频")
        self.download_mp3_btn.clicked.connect(lambda: self.start_download('mp3'))
        
        self.download_mp4_btn = QPushButton("下载MP4视频")
        self.download_mp4_btn.clicked.connect(lambda: self.start_download('mp4'))
        
        self.download_m4a_btn = QPushButton("下载MP4音频")
        self.download_m4a_btn.clicked.connect(lambda: self.start_download('mp4audio'))
        
        # 添加新按钮
        self.download_full_mp4_btn = QPushButton("下载MP4音视频")
        self.download_full_mp4_btn.clicked.connect(lambda: self.start_download('full_mp4'))
        
        self.open_folder_btn = QPushButton("打开下载文件夹")
        self.open_folder_btn.clicked.connect(self.open_download_folder)
        self.open_folder_btn.setEnabled(False)
        
        # 进度条和状态标签
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.status_label = QLabel("等待下载...")
        self.status_label.setObjectName("statusLabel")  # 设置对象名，用于CSS样式
        self.status_label.setMinimumHeight(80)  # 设置最小高度
        self.status_label.setAlignment(Qt.AlignCenter)  # 文字居中
        self.status_label.setWordWrap(True)  # 允许文字换行
        
        # 添加样式
        status_style = """
        QLabel#statusLabel {
            background-color: #f0f9f0;  /* 浅绿色背景 */
            border: 1px solid #90EE90;  /* 浅绿色边框 */
            border-radius: 5px;         /* 圆角 */
            padding: 10px;              /* 内边距 */
            color: #2E8B57;            /* 深绿色文字 */
            font-size: 14px;           /* 字体大小 */
        }
        """
        self.status_label.setStyleSheet(status_style)
        
        # 剪辑部分控件
        self.file_path_input = QLineEdit()
        self.file_path_input.setPlaceholderText("选择要剪辑的视频文件...")
        self.file_path_input.setReadOnly(True)
        
        self.select_file_btn = QPushButton("选择文件")
        self.select_file_btn.clicked.connect(self.select_file)
        
        self.start_time = QTimeEdit()
        self.start_time.setDisplayFormat("HH:mm:ss")
        self.end_time = QTimeEdit()
        self.end_time.setDisplayFormat("HH:mm:ss")
        
        self.clip_audio_btn = QPushButton("剪辑音频")
        self.clip_audio_btn.clicked.connect(lambda: self.start_clip(True))
        self.clip_video_btn = QPushButton("剪辑视频")
        self.clip_video_btn.clicked.connect(lambda: self.start_clip(False))
        
        # 拼接部分控件
        self.concat_file1_input = QLineEdit()
        self.concat_file1_input.setPlaceholderText("选择第一文件...")
        self.concat_file1_input.setReadOnly(True)
        
        self.concat_file2_input = QLineEdit()
        self.concat_file2_input.setPlaceholderText("选择第二个文件...")
        self.concat_file2_input.setReadOnly(True)
        
        self.select_concat_file1_btn = QPushButton("选择文件1")
        self.select_concat_file1_btn.clicked.connect(lambda: self.select_concat_file(1))
        
        self.select_concat_file2_btn = QPushButton("选择文件2")
        self.select_concat_file2_btn.clicked.connect(lambda: self.select_concat_file(2))
        
        self.concat_start_time1 = QTimeEdit()
        self.concat_start_time1.setDisplayFormat("HH:mm:ss")
        self.concat_end_time1 = QTimeEdit()
        self.concat_end_time1.setDisplayFormat("HH:mm:ss")
        
        self.concat_start_time2 = QTimeEdit()
        self.concat_start_time2.setDisplayFormat("HH:mm:ss")
        self.concat_end_time2 = QTimeEdit()
        self.concat_end_time2.setDisplayFormat("HH:mm:ss")
        
        # 拼接按钮布局
        concat_buttons_layout = QHBoxLayout()

        self.concat_video_btn = QPushButton("视频拼接")
        self.concat_video_btn.setEnabled(False)
        self.concat_video_btn.clicked.connect(lambda: self.start_concat('video'))

        self.concat_video_only_btn = QPushButton("纯视频拼接")
        self.concat_video_only_btn.setEnabled(False)
        self.concat_video_only_btn.clicked.connect(lambda: self.start_concat('video_only'))

        self.concat_audio_btn = QPushButton("音频拼接")
        self.concat_audio_btn.setEnabled(False)
        self.concat_audio_btn.clicked.connect(lambda: self.start_concat('audio'))

        concat_buttons_layout.addStretch()
        concat_buttons_layout.addWidget(self.concat_video_btn)
        concat_buttons_layout.addWidget(self.concat_video_only_btn)
        concat_buttons_layout.addWidget(self.concat_audio_btn)
        concat_buttons_layout.addStretch()

        # 加载样式表
        if getattr(sys, 'frozen', False):
            current_dir = os.path.dirname(sys.executable)
        else:
            current_dir = os.path.dirname(os.path.abspath(__file__))
        
        style_path = os.path.join(current_dir, 'style.qss')
        try:
            with open(style_path, 'r', encoding='utf-8') as f:
                style = f.read()
                self.setStyleSheet(style)
        except Exception as e:
            print(f"加载样式表失败: {str(e)}")
        
        # 创建布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(0)
        
        # 创建一个滚动区
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setFrameShape(QFrame.NoFrame)  # 移除边框
        
        # 创建内容容器
        content_widget = QWidget()
        content_widget.setObjectName("contentWidget")
        content_layout = QVBoxLayout(content_widget)
        content_layout.setSpacing(10)
        content_layout.setContentsMargins(10, 10, 10, 10)
        
        # 下载部分布局
        download_button_layout = QHBoxLayout()
        download_button_layout.addWidget(self.download_mp3_btn)
        download_button_layout.addWidget(self.download_m4a_btn)
        download_button_layout.addWidget(self.download_mp4_btn)
        download_button_layout.addWidget(self.download_full_mp4_btn)
        download_button_layout.addWidget(self.open_folder_btn)
        
        # 剪辑部分布局
        clip_file_layout = QHBoxLayout()
        clip_file_layout.addWidget(self.file_path_input)
        clip_file_layout.addWidget(self.select_file_btn)
        
        time_layout = QHBoxLayout()
        time_layout.addWidget(QLabel("开始时间:"))
        time_layout.addWidget(self.start_time)
        time_layout.addWidget(QLabel("结束时间:"))
        time_layout.addWidget(self.end_time)
        time_layout.addWidget(self.clip_audio_btn)
        time_layout.addWidget(self.clip_video_btn)
        
        # 拼接部分布局
        concat_file1_layout = QHBoxLayout()
        concat_file1_layout.addWidget(self.concat_file1_input)
        concat_file1_layout.addWidget(self.select_concat_file1_btn)
        
        time1_layout = QHBoxLayout()
        time1_layout.addWidget(QLabel("开始时间:"))
        time1_layout.addWidget(self.concat_start_time1)
        time1_layout.addWidget(QLabel("结束时:"))
        time1_layout.addWidget(self.concat_end_time1)
        
        concat_file2_layout = QHBoxLayout()
        concat_file2_layout.addWidget(self.concat_file2_input)
        concat_file2_layout.addWidget(self.select_concat_file2_btn)
        
        time2_layout = QHBoxLayout()
        time2_layout.addWidget(QLabel("开始时间:"))
        time2_layout.addWidget(self.concat_start_time2)
        time2_layout.addWidget(QLabel("结束时间:"))
        time2_layout.addWidget(self.concat_end_time2)
        
        # 添加所有控件到 content_layout
        # 1. 下载部分
        content_layout.addWidget(QLabel("视频链接:"))
        content_layout.addWidget(self.url_input)
        content_layout.addLayout(download_button_layout)
        content_layout.addWidget(self.progress_bar)
        content_layout.addWidget(self.status_label)

        # 添加分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        content_layout.addWidget(line)

        # 2. 剪辑部分
        content_layout.addWidget(QLabel("剪辑文件:"))
        content_layout.addLayout(clip_file_layout)
        content_layout.addLayout(time_layout)

        # 添加分隔线
        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        line2.setFrameShadow(QFrame.Sunken)
        content_layout.addWidget(line2)

        # 3. 拼接部分（移到最后）
        content_layout.addWidget(QLabel("视频拼接:"))
        content_layout.addLayout(concat_file1_layout)
        content_layout.addLayout(time1_layout)
        content_layout.addLayout(concat_file2_layout)
        content_layout.addLayout(time2_layout)
        content_layout.addLayout(concat_buttons_layout)

        # 设置滚动区域的内容
        scroll_area.setWidget(content_widget)

        # 将滚动区域添加到主布局
        main_layout.addWidget(scroll_area)
        
        # 初始化其他属性
        self.last_download_path = None
        self.active_workers = []
        self.is_closing = False

    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择要剪辑的文件",
            "",
            "所有支持的文件 (*.mp3 *.MP3 *.mp4 *.MP4);;视频文件 (*.mp4 *.MP4);;音频文件 (*.mp3 *.MP3)"
        )
        if file_path:
            self.file_path_input.setText(file_path)
            try:
                duration = None
                if file_path.lower().endswith('.mp4'):
                    # 先尝试作为音频文件打开
                    try:
                        audio = AudioFileClip(file_path)
                        duration = int(audio.duration)
                        audio.close()
                        has_audio = True
                    except:
                        has_audio = False

                    # 再尝试作为视频文件打开
                    try:
                        video = VideoFileClip(file_path)
                        if duration is None:
                            duration = int(video.duration)
                        has_video = video.size[0] > 0 and video.size[1] > 0
                        # 如果之前没检测到音频，再次检查视频文件的音频
                        if not has_audio:
                            has_audio = video.audio is not None
                        video.close()
                    except:
                        has_video = False
                        if not has_audio:
                            self.status_label.setText("无法读取文件：既不是有效的频也不是有效的音频")
                            return

                    # 根据文件包含的流类型启用相应按钮
                    if has_video:
                        self.clip_video_btn.setEnabled(True)
                        if has_audio:
                            self.clip_audio_btn.setEnabled(True)
                            self.status_label.setText("MP4文件（音视频）加载成功")
                        else:
                            self.clip_audio_btn.setEnabled(False)
                            self.status_label.setText("MP4文件（仅视频）加载成功")
                    else:
                        self.clip_video_btn.setEnabled(False)
                        if has_audio:
                            self.clip_audio_btn.setEnabled(True)
                            self.status_label.setText("MP4文件（仅音频）加载成功")
                        else:
                            self.clip_audio_btn.setEnabled(False)
                            self.status_label.setText("无效的MP4文件")
                            return

                else:  # MP3文件
                    try:
                        audio = AudioFileClip(file_path)
                        duration = int(audio.duration)
                        audio.close()
                        self.clip_audio_btn.setEnabled(True)
                        self.clip_video_btn.setEnabled(False)
                        self.status_label.setText("音频文件加载成功")
                    except Exception as e:
                        self.status_label.setText(f"读取音频文件失败: {str(e)}")
                        return

                # 设置结束时间
                if duration is not None:
                    hours = duration // 3600
                    minutes = (duration % 3600) // 60
                    seconds = duration % 60
                    self.end_time.setTime(QTime(hours, minutes, seconds))
                
            except Exception as e:
                self.status_label.setText(f"读取文件失败: {str(e)}")

    def start_clip(self, audio_only=False):
        file_path = self.file_path_input.text()
        if not file_path:
            self.status_label.setText("请先选择文件！")
            return
        
        # 获取时间值（转换为秒）
        start = self.start_time.time()
        end = self.end_time.time()
        start_seconds = start.hour() * 3600 + start.minute() * 60 + start.second()
        end_seconds = end.hour() * 3600 + end.minute() * 60 + end.second()
        
        if start_seconds >= end_seconds:
            self.status_label.setText("开始时间必须小于结束时间！")
            return
        
        # 如果是音频剪辑且文件是MP4，检查是否包含音频流
        if audio_only and file_path.lower().endswith('.mp4'):
            worker = ClipWorker(file_path, 0, 0, True)
            has_video, has_audio = worker.has_video_stream(file_path)
            
            if has_audio:
                # 有音频流，让用户选择输出格式
                msg_box = QMessageBox(self)
                msg_box.setWindowTitle('选择输出格式')
                msg_box.setText('请选择音频输出格式：')
                
                mp3_btn = msg_box.addButton('MP3格式', QMessageBox.ActionRole)
                mp4_btn = msg_box.addButton('MP4格式', QMessageBox.ActionRole)
                # 添加隐藏的取消按钮
                hidden_cancel_btn = msg_box.addButton('', QMessageBox.RejectRole)
                hidden_cancel_btn.hide()
                
                style = """
                QPushButton {
                    padding-left: 20px;
                    padding-right: 20px;
                    margin-left: 10px;
                    margin-right: 10px;
                }
                """
                mp3_btn.setStyleSheet(style)
                mp4_btn.setStyleSheet(style)
                
                msg_box.exec()
                
                clicked_button = msg_box.clickedButton()
                if clicked_button is None or clicked_button == hidden_cancel_btn:
                    return  # 用户关闭对话框，取消操作
                
                # 禁用按钮
                self.clip_audio_btn.setEnabled(False)
                self.clip_video_btn.setEnabled(False)
                
                # 创建worker并设置正确的输出格式
                worker = ClipWorker(file_path, start_seconds, end_seconds, True)
                worker.save_as_mp4_audio = (clicked_button == mp4_btn)  # 根据用户选择设置输出格式
                worker.progress_signal.connect(self.update_status)
                worker.finished_signal.connect(lambda msg: self.task_finished(worker, msg))
                self.active_workers.append(worker)
                worker.start()
                return
            
            else:
                # 没有音频流，提示用户
                QMessageBox.warning(self, "警告", "所选MP4文件不包含音频流！")
                return
        
        # 如果是视频剪辑且文件是MP4，检查是否包含音频流
        elif not audio_only and file_path.lower().endswith('.mp4'):
            worker = ClipWorker(file_path, 0, 0, True)
            has_video, has_audio = worker.has_video_stream(file_path)
            
            if has_video and has_audio:
                # 有视频和音频流，让用户选择输出格式
                msg_box = QMessageBox(self)
                msg_box.setWindowTitle('选择输出格式')
                msg_box.setText('请选择视频输出格式：')
                
                video_btn = msg_box.addButton('视频MP4', QMessageBox.ActionRole)
                video_audio_btn = msg_box.addButton('音视频MP4', QMessageBox.ActionRole)
                # 添加隐藏的取消按钮
                hidden_cancel_btn = msg_box.addButton('', QMessageBox.RejectRole)
                hidden_cancel_btn.hide()
                
                style = """
                QPushButton {
                    padding-left: 20px;
                    padding-right: 20px;
                    margin-left: 10px;
                    margin-right: 10px;
                }
                """
                video_btn.setStyleSheet(style)
                video_audio_btn.setStyleSheet(style)
                
                msg_box.exec()
                
                clicked_button = msg_box.clickedButton()
                if clicked_button is None or clicked_button == hidden_cancel_btn:
                    return  # 用户关闭对话框，取消操作
                
                # 禁用按钮
                self.clip_audio_btn.setEnabled(False)
                self.clip_video_btn.setEnabled(False)
                
                # 创建worker并设置正确的输出格式
                worker = ClipWorker(file_path, start_seconds, end_seconds, False)
                worker.video_only = (clicked_button == video_btn)  # 根据用户选择设置是否只保留视频
                worker.progress_signal.connect(self.update_status)
                worker.finished_signal.connect(lambda msg: self.task_finished(worker, msg))
                self.active_workers.append(worker)
                worker.start()
                return
        
        # 如果��MP3文件或其他情况��音频剪辑
        # 禁用按钮
        self.clip_audio_btn.setEnabled(False)
        self.clip_video_btn.setEnabled(False)
        
        # 开始剪辑
        worker = ClipWorker(file_path, start_seconds, end_seconds, audio_only)
        worker.progress_signal.connect(self.update_status)
        worker.finished_signal.connect(lambda msg: self.task_finished(worker, msg))
        
        self.active_workers.append(worker)
        worker.start()

    def task_finished(self, worker, message):
        """统一处理任务完成事件"""
        if worker in self.active_workers:
            self.active_workers.remove(worker)
        
        if isinstance(worker, DownloadWorker):
            self.download_finished(message)
        else:
            self.clip_finished(message)
            
        # 如果是在关闭窗口的过程中，且没有其他活动任务，则关闭窗口
        if self.is_closing and not self.active_workers:
            self.close()

    def start_download(self, download_type):
        url = self.url_input.text().strip()
        if not url:
            self.status_label.setText("请输入视频链接！")
            return
        
        self.progress_bar.setValue(0)
        
        # 禁用所有下��按钮
        self.download_mp3_btn.setEnabled(False)
        self.download_mp4_btn.setEnabled(False)
        self.download_m4a_btn.setEnabled(False)
        self.download_full_mp4_btn.setEnabled(False)
        self.open_folder_btn.setEnabled(False)
        
        worker = DownloadWorker(url, download_type)
        worker.progress_signal.connect(self.update_status)
        worker.progress_value.connect(self.update_progress)
        worker.finished_signal.connect(lambda msg: self.task_finished(worker, msg))
        
        self.active_workers.append(worker)
        worker.start()

    def update_status(self, message):
        self.status_label.setText(message)

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def download_finished(self, message):
        """下载完成处理"""
        if not self.is_closing:
            self.status_label.setText(message)
            # 重新启用所有下载按钮
            self.download_mp3_btn.setEnabled(True)
            self.download_mp4_btn.setEnabled(True)
            self.download_m4a_btn.setEnabled(True)
            self.download_full_mp4_btn.setEnabled(True)
            
            if "载完成" in message:
                self.progress_bar.setValue(100)
                self.open_folder_btn.setEnabled(True)
                self.last_download_path = os.path.dirname(message.split(": ")[1])

    def clip_finished(self, message):
        """剪辑完成理"""
        if not self.is_closing:
            self.status_label.setText(message)
            self.clip_audio_btn.setEnabled(True)
            self.clip_video_btn.setEnabled(True)

    def open_download_folder(self):
        if self.last_download_path and os.path.exists(self.last_download_path):
            if sys.platform == 'win32':
                os.startfile(self.last_download_path)
            elif sys.platform == 'darwin':
                subprocess.run(['open', self.last_download_path])
            else:
                subprocess.run(['xdg-open', self.last_download_path])

    def closeEvent(self, event):
        """窗口关闭事件处理"""
        if self.active_workers:
            self.is_closing = True
            reply = QMessageBox.question(
                self,
                '确认退出',
                '有正在进行的任务，确定要退出吗？\n选择"是"立即退出\n选择"否"等待任务完成后退出\n选择"取消"继续运行',
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Cancel
            )
            
            if reply == QMessageBox.Yes:
                # 立即终止所有任务并退出
                self.terminate_all_tasks()
                event.accept()
            elif reply == QMessageBox.No:
                # 等任务完成
                self.wait_for_tasks()
                event.accept()
            else:
                # 取消关
                self.is_closing = False
                event.ignore()
        else:
            event.accept()

    def terminate_all_tasks(self):
        """终止所有活动任务"""
        for worker in self.active_workers:
            try:
                if isinstance(worker, ClipWorker):
                    # 对于剪辑任务，需要确保文件被正确关闭
                    if hasattr(worker, 'media'):
                        worker.media.close()
                    if hasattr(worker, 'clip'):
                        worker.clip.close()
                worker.terminate()
                worker.wait()
            except Exception as e:
                print(f"终止任务时出错: {str(e)}")
        self.active_workers.clear()

    def wait_for_tasks(self):
        """等待所有务完成"""
        for worker in self.active_workers:
            worker.wait()
        self.active_workers.clear()

    def select_concat_file(self, file_num):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            f"选择第{file_num}个文件",
            "",
            "音频文件 (*.mp3 *.MP3 *.mp4 *.MP4)"
        )
        if file_path:
            try:
                duration = None
                has_audio = False
                has_video = False

                if file_path.lower().endswith('.mp4'):
                    # 先尝试作为音频文件打开
                    try:
                        audio = AudioFileClip(file_path)
                        duration = int(audio.duration)
                        audio.close()
                        has_audio = True
                    except:
                        pass

                    # 再尝试作为视频文件打开
                    try:
                        video = VideoFileClip(file_path)
                        if duration is None:
                            duration = int(video.duration)
                        has_video = video.size[0] > 0 and video.size[1] > 0
                        # 如果之前没检测到音频，再次检查视频文件的音频
                        if not has_audio:
                            has_audio = video.audio is not None
                        video.close()
                    except:
                        if not has_audio:
                            self.status_label.setText("无法读取文件：既不是有效的视频也不是有效的音频")
                            return
                else:  # MP3文件
                    try:
                        audio = AudioFileClip(file_path)
                        duration = int(audio.duration)
                        audio.close()
                        has_audio = True
                    except Exception as e:
                        self.status_label.setText(f"读取音频文件失败: {str(e)}")
                        return

                # 设文件路径和时长
                if file_num == 1:
                    self.concat_file1_input.setText(file_path)
                    self.concat_end_time1.setTime(QTime(duration // 3600, (duration % 3600) // 60, duration % 60))
                else:
                    self.concat_file2_input.setText(file_path)
                    self.concat_end_time2.setTime(QTime(duration // 3600, (duration % 3600) // 60, duration % 60))

                # 如果两个文件都已选择，根据文件类型启用相应按钮
                if self.concat_file1_input.text() and self.concat_file2_input.text():
                    file1_is_video = self.concat_file1_input.text().lower().endswith('.mp4') and \
                                    self._check_file_has_video(self.concat_file1_input.text())
                    file2_is_video = self.concat_file2_input.text().lower().endswith('.mp4') and \
                                    self._check_file_has_video(self.concat_file2_input.text())

                    # 如果都是视频文件，启用所有视频相关按钮
                    if file1_is_video and file2_is_video:
                        self.concat_video_btn.setEnabled(True)
                        self.concat_video_only_btn.setEnabled(True)
                    else:
                        self.concat_video_btn.setEnabled(False)
                        self.concat_video_only_btn.setEnabled(False)

                    # 音频拼接按钮始终可用
                    self.concat_audio_btn.setEnabled(True)

            except Exception as e:
                self.status_label.setText(f"读取文件失败: {str(e)}")

    def _check_file_has_video(self, file_path):
        """检查MP4文件是否包含视频流"""
        try:
            video = VideoFileClip(file_path)
            has_video = video.size[0] > 0 and video.size[1] > 0
            video.close()
            return has_video
        except:
            return False

    def start_concat(self, concat_type):
        # 获取文件路径和时间值
        file1 = self.concat_file1_input.text()
        file2 = self.concat_file2_input.text()
        
        # 获取时间值
        start1 = self.concat_start_time1.time()
        end1 = self.concat_end_time1.time()
        start2 = self.concat_start_time2.time()
        end2 = self.concat_end_time2.time()
        
        # 转换为秒
        start_seconds1 = start1.hour() * 3600 + start1.minute() * 60 + start1.second()
        end_seconds1 = end1.hour() * 3600 + end1.minute() * 60 + end1.second()
        start_seconds2 = start2.hour() * 3600 + start2.minute() * 60 + start2.second()
        end_seconds2 = end2.hour() * 3600 + end2.minute() * 60 + end2.second()
        
        # 验证时间
        if start_seconds1 >= end_seconds1 or start_seconds2 >= end_seconds2:
            self.status_label.setText("开始时间必须小于结束时间！")
            return
        
        # 如果是音频拼接，先让用户选择输出格式
        if concat_type == 'audio':
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle('选择输出格式')
            msg_box.setText('请选择音频输出格式：')
            
            mp3_btn = msg_box.addButton('MP3格式', QMessageBox.ActionRole)
            mp4_btn = msg_box.addButton('MP4格式', QMessageBox.ActionRole)
            # 添加隐藏的取消按钮
            hidden_cancel_btn = msg_box.addButton('', QMessageBox.RejectRole)
            hidden_cancel_btn.hide()
            
            style = """
            QPushButton {
                padding-left: 20px;
                padding-right: 20px;
                margin-left: 10px;
                margin-right: 10px;
            }
            """
            mp3_btn.setStyleSheet(style)
            mp4_btn.setStyleSheet(style)
            
            msg_box.exec()
            
            clicked_button = msg_box.clickedButton()
            if clicked_button is None or clicked_button == hidden_cancel_btn:
                return  # 用户关闭对话框或点击X，取消操作
            elif clicked_button == mp3_btn:
                concat_type = 'audio_mp3'
            else:  # clicked_button == mp4_btn
                concat_type = 'audio_mp4'
        
        # 禁用所有拼接按钮
        self.concat_video_btn.setEnabled(False)
        self.concat_video_only_btn.setEnabled(False)
        self.concat_audio_btn.setEnabled(False)
        
        # 创建并启动工作线程
        worker = ConcatWorker(file1, file2, start_seconds1, end_seconds1, 
                            start_seconds2, end_seconds2, concat_type)
        worker.progress_signal.connect(self.update_status)
        worker.finished_signal.connect(lambda msg: self.concat_finished(worker, msg))
        
        self.active_workers.append(worker)
        worker.start()

    def concat_finished(self, worker, message):
        if worker in self.active_workers:
            self.active_workers.remove(worker)
        
        if not self.is_closing:
            self.status_label.setText(message)
            # 重新启用所有拼接按钮
            file1_is_video = self.concat_file1_input.text().lower().endswith('.mp4')
            file2_is_video = self.concat_file2_input.text().lower().endswith('.mp4')
            
            # 如果都是视频文件，启用所有视频相关按钮
            if file1_is_video and file2_is_video:
                self.concat_video_btn.setEnabled(True)
                self.concat_video_only_btn.setEnabled(True)
            
            # 音频拼接按钮始终可用
            self.concat_audio_btn.setEnabled(True)
            
        if self.is_closing and not self.active_workers:
            self.close()

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

