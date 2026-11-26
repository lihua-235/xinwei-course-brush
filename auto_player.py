"""
auto_player.py - 自动化刷课核心模块（v17 最终版）
核心: 步长30秒 + 间隔30秒 = 模拟1x正常播放
"""

import json
import time
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from urllib.parse import urljoin
import requests

logger = logging.getLogger(__name__)


@dataclass
class VideoNode:
    item_id: str
    title: str
    resource_id: str
    total_time: int
    study_time: int
    status: int
    rate_enum: str
    
    @property
    def total_milliseconds(self) -> int:
        return (self.total_time or 0) * 1000
    
    @property
    def is_completed(self) -> bool:
        return self.status == 2
    
    @property
    def progress_percent(self) -> float:
        study = self.study_time or 0
        total = self.total_time or 1
        if total == 0:
            return 0
        return (study / total) * 100


@dataclass
class Chapter:
    chapter_id: str
    title: str
    status: int
    videos: List[VideoNode] = field(default_factory=list)


class AutoPlayer:
    """自动刷课客户端"""
    
    BASE_URL = "https://www.beeline-ai.com"
    STEP_SIZE = 30
    REPORT_INTERVAL = 30
    
    def __init__(self, session, class_id, course_id, sso_id, debug=False, relogin=None):
        self.session = session
        self.teaching_class_id = class_id
        self.teaching_course_id = course_id
        self.user_sso_id = sso_id
        self.debug = debug
        # 401 时用于自动重新登录的回调，返回 True 表示登录成功
        self.relogin = relogin
        
        # 清理重复Cookie
        self._clean_cookies()
        
        self.session.headers.update({
            'Content-Type': 'application/json;charset=UTF-8',
        })
        
        self.stats = {...}

    def _clean_cookies(self):
        """移除重复的Cookie，只保留最后一个"""
        seen = {}
        cookies_to_keep = []
        for cookie in self.session.cookies:
            if cookie.name in seen:
                # 重复了，跳过旧的
                continue
            seen[cookie.name] = cookie
            cookies_to_keep.append(cookie)
        
        # 清空并重新设置
        self.session.cookies.clear()
        for cookie in cookies_to_keep:
            self.session.cookies.set_cookie(cookie)
    
    def _post(self, endpoint: str, data: Dict) -> Dict:
        url = urljoin(self.BASE_URL, endpoint)
        try:
            if self.debug:
                print(f"\n{'='*60}")
                print(f"📤 POST {endpoint}")
                print(f"Headers: {dict(self.session.headers)}")
                print(f"Cookies: {dict(self.session.cookies)}")
                print(f"Body: {json.dumps(data, ensure_ascii=False, indent=2)}")
            
            response = self.session.post(url, json=data, timeout=30)
            if response.status_code == 401 and self.relogin:
                logger.warning("⚠️ Token 失效(401)，自动重新登录...")
                if self.relogin():
                    logger.info("✅ 重新登录成功，重试请求")
                    response = self.session.post(url, json=data, timeout=30)
            
            if self.debug:
                print(f"---")
                print(f"⬅ Status: {response.status_code}")
                print(f"Response Headers: {dict(response.headers)}")
                print(f"Response Body: {response.text[:1000]}")
                print(f"{'='*60}\n")
            
            response.raise_for_status()
            return response.json()
        except Exception as e:
            if self.debug:
                print(f"❌ 失败: {e}")
            return {"code": 500, "msg": str(e)}

    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        url = urljoin(self.BASE_URL, endpoint)
        try:
            if self.debug:
                print(f"\n{'='*60}")
                print(f"📤 GET {endpoint}")
                if params:
                    print(f"Params: {params}")
            
            response = self.session.get(url, params=params, timeout=30)
            if response.status_code == 401 and self.relogin:
                logger.warning("⚠️ Token 失效(401)，自动重新登录...")
                if self.relogin():
                    logger.info("✅ 重新登录成功，重试请求")
                    response = self.session.get(url, params=params, timeout=30)
            
            if self.debug:
                print(f"⬅ Status: {response.status_code}")
                print(f"Response: {response.text[:500]}")
                print(f"{'='*60}\n")
            
            response.raise_for_status()
            return response.json()
        except Exception as e:
            if self.debug:
                print(f"❌ 失败: {e}")
            return {"code": 500, "msg": str(e)}
    
    def enter_class(self) -> bool:
        endpoint = "/api/learning-service/manager/collect/teachingClass/enterClass"
        data = {"teachingClassId": self.teaching_class_id}
        response = self._post(endpoint, data)
        if response.get('code') == 200:
            logger.info(f"✅ 进入课程成功")
            return True
        logger.error(f"❌ 进入课程失败: {response}")
        return False
    
    @staticmethod
    def _extract_videos(node: Dict) -> List[Dict]:
        """
        递归提取真正的视频资源节点。
        平台接口是三层树：章(type=0) → 节(type=1) → 资源(type=2)
        其中 type=2 且 totalTime>0 的才是视频（PDF 课件 totalTime=0）。
        同时兼容旧的扁平结构（节节点自带 totalTime）。
        """
        if not isinstance(node, dict):
            return []
        out: List[Dict] = []
        for child in node.get('children') or []:
            out.extend(AutoPlayer._extract_videos(child))
        if out:
            return out
        total_time = node.get('totalTime')
        if total_time:
            return [node]
        return []

    def get_chapter_data(self) -> List[Chapter]:
        endpoint = "/api/learning-service/admin/studentLearning/getChapterData"
        data = {"teachingClassId": self.teaching_class_id}
        
        response = self._post(endpoint, data)
        if response.get('code') != 200:
            logger.error(f"获取章节失败: {response}")
            return []
        
        chapters = []
        for chapter_data in response.get('data', []):
            chapter = Chapter(
                chapter_id=chapter_data.get('id', ''),
                title=chapter_data.get('title', ''),
                status=chapter_data.get('status', 1)
            )
            for child in chapter_data.get('children', []):
                for video_data in self._extract_videos(child):
                    video = VideoNode(
                        item_id=video_data.get('id', ''),
                        title=video_data.get('title', ''),
                        resource_id=video_data.get('resourceId', ''),
                        total_time=video_data.get('totalTime') or 0,
                        study_time=video_data.get('studyTime') or 0,
                        status=video_data.get('status', 1),
                        rate_enum=video_data.get('rateEnum', '0')
                    )
                    chapter.videos.append(video)
            chapters.append(chapter)
        return chapters
    
    def _report_once(self, item_id: str, total_ms: int, start_pos: float, 
                     end_pos: float, record_count: int) -> Tuple[bool, int]:
        endpoint = "/api/learning-service/admin/studentLearning/videoLearnProcessReport"
        
        payload = {
            "itemId": item_id,
            "teachingClassId": self.teaching_class_id,
            "teachingCourseId": self.teaching_course_id,
            "userSsoId": self.user_sso_id,
            "videoMilSeconds": total_ms,
            "startPosition": round(start_pos, 6),
            "endPosition": round(end_pos, 6),
            "playPosition": round(end_pos, 6),
            "playbackRate": 1,
            "recordCount": 30,
            "platform": "web"
        }
        
        response = self._post(endpoint, payload)
        
        if response.get('code') == 200:
            result_code = response.get('data', 1)
            return True, result_code
        else:
            logger.error(f"  上报失败: {response.get('msg')}")
            return False, 0
    
    def _record_learning(self) -> bool:
        endpoint = "/api/learning-service/outline/recordLearning"
        params = {"classId": self.teaching_class_id}
        response = self._get(endpoint, params)
        if response.get('code') == 200:
            logger.info(f"  ✅ recordLearning 成功")
            return True
        logger.warning(f"  recordLearning 失败: {response}")
        return False
    
    def _get_examine_data(self):
        endpoint = "/api/learning-service/admin/studentLearning/getExamineData"
        data = {"teachingClassId": self.teaching_class_id}
        response = self._post(endpoint, data)
        if response.get('code') == 200:
            exam_data = response.get('data', {})
            complete = exam_data.get('chapterExamineComplete', '?')
            logger.info(f"  ✅ examine chapterComplete={complete}")
            return complete
        return None
    
    def _switch_video(self, item_id: str) -> bool:
        """告诉服务端切换到指定视频"""
        endpoint = f"/api/learning-service/admin/studentLearning/getSingleChapterData/{item_id}"
        response = self._post(endpoint, {})  # 改成POST，带空body
        if response.get('code') == 200:
            logger.info(f"   ✅ 切换视频成功")
            return True
        logger.warning(f"   切换视频失败: {response}")
        return False

    def complete_video(self, video: VideoNode) -> bool:
        if video.is_completed:
            logger.info(f"⏭️ 已完成，跳过: {video.title}")
            return True
        
        total_time = float(video.total_time)
        total_ms = video.total_milliseconds
        item_id = video.item_id
        
        current_pos = float(video.study_time)
        record_count = 30
        examine_triggered = False
        
        logger.info(f"▶️ {video.title}")
        logger.info(f"   {current_pos:.0f}s → {total_time:.0f}s | 步长:{self.STEP_SIZE}s | 间隔:{self.REPORT_INTERVAL}s")

        self._switch_video(video.item_id)

        # 切换视频后等待30秒
        logger.info(f"   ⏳ 等待30秒后开始上报...")
        time.sleep(30)
        
        # 起始上报
        if current_pos > 0:
            logger.info(f"   [起始上报] pos={current_pos:.1f}s, recordCount={record_count}")
            success, _ = self._report_once(
                item_id, total_ms, current_pos, current_pos, record_count
            )
            if not success:
                logger.error(f"❌ 起始上报失败")
                return False
            record_count = 30
            time.sleep(30)
        
        while current_pos < total_time:
            new_pos = min(current_pos + self.STEP_SIZE, total_time)
            percent = new_pos / total_time * 100 if total_time > 0 else 0
            
            success, result_code = self._report_once(
                item_id, total_ms, current_pos, new_pos, record_count
            )
            
            if not success:
                logger.error(f"❌ 上报失败")
                return False
            
            record_count += 1
            current_pos = new_pos
            
            logger.info(f"   {current_pos:.0f}/{total_time:.0f}s ({percent:.1f}%) | data={result_code}")
            
            if not examine_triggered and percent >= 80:
                examine_triggered = True
                logger.info(f"   🎉 达到80%")
                self._get_examine_data()
            
            if current_pos >= total_time:
                break
            
            time.sleep(self.REPORT_INTERVAL)
        
        # 完成确认
        logger.info(f"🏁 100%，确认流程...")
        time.sleep(1)
        self._record_learning()
        time.sleep(1)
        self._get_examine_data()
        time.sleep(2)
        self._report_once(item_id, total_ms, current_pos, current_pos, record_count)
        
        logger.info(f"✅ {video.title}")
        return True
    
    def show_progress(self):
        chapters = self.get_chapter_data()
        
        total_videos = 0
        completed_videos = 0
        
        print(f"\n{'='*60}")
        print(f"📚 课程进度")
        print(f"{'='*60}")
        
        for chapter in chapters:
            print(f"\n📖 {chapter.title}")
            for video in chapter.videos:
                total_videos += 1
                if video.is_completed:
                    completed_videos += 1
                    status = "✅"
                else:
                    status = "⏳"
                print(f"  {status} {video.title} ({video.study_time}s/{video.total_time}s)")
        
        print(f"\n{'='*60}")
        print(f"总计: {completed_videos}/{total_videos} 完成")
        print(f"{'='*60}")
    
    def complete_all_videos(self, skip_completed: bool = True,
                        target_titles: Optional[List[str]] = None) -> Dict:
        chapters = self.get_chapter_data()
        
        self.stats = {
            'total_videos': 0,
            'completed_videos': 0,
            'failed_videos': 0,
            'skipped_videos': 0,
        }
        
        # 获取服务端锁定的视频
        last_chapter_id = self._get_last_chapter()
        locked_video = self._find_video_by_chapter_id(chapters, last_chapter_id)
        
        for chapter in chapters:
            for video in chapter.videos:
                if target_titles and video.title not in target_titles:
                    continue
                
                self.stats['total_videos'] += 1
                
                if skip_completed and video.is_completed:
                    self.stats['skipped_videos'] += 1
                    continue
                
                try:
                    logger.info(f"\n{'='*50}")
                    
                    # 如果服务端锁定的视频和当前要学的不同，先结束旧视频
                    if locked_video and locked_video.item_id != video.item_id:
                        logger.info(f"🔓 结束旧视频: {locked_video.title}")
                        self._end_video(locked_video)
                        locked_video = None
                        time.sleep(2)
                    
                    # 进入课程
                    logger.info("📡 进入课程...")
                    self.enter_class()
                    time.sleep(1)
                    self._get_examine_data()
                    time.sleep(2)
                    
                    success = self.complete_video(video)
                    if success:
                        self.stats['completed_videos'] += 1
                        locked_video = video
                    else:
                        self.stats['failed_videos'] += 1
                        self.enter_class()
                        time.sleep(3)
                        
                except KeyboardInterrupt:
                    logger.info("\n⚠️ 用户中断")
                    return self.stats
                except Exception as e:
                    logger.error(f"异常: {video.title} - {e}")
                    self.stats['failed_videos'] += 1
                    self.enter_class()
                    time.sleep(3)
        
        return self.stats

    def _get_last_chapter(self) -> Optional[str]:
        """获取服务端记录的lastChapter"""
        endpoint = "/api/learning-service/admin/studentLearning/getExamineData"
        data = {"teachingClassId": self.teaching_class_id}
        response = self._post(endpoint, data)
        if response.get('code') == 200:
            last_chapter = response.get('data', {}).get('lastChapter')
            logger.info(f"   lastChapter: {last_chapter}")
            return last_chapter
        return None

    def _find_video_by_chapter_id(self, chapters: List[Chapter], chapter_id: str) -> Optional[VideoNode]:
        """根据chapter_id找到对应的视频"""
        if not chapter_id:
            return None
        for chapter in chapters:
            for video in chapter.videos:
                if video.item_id == chapter_id:  # itemId就是视频的id
                    return video
        return None

    def _end_video(self, video: VideoNode):
        """模拟切换视频时的最后一次上报"""
        # 使用studyTime作为当前进度
        current = float(video.study_time)
        if current == 0:
            # studyTime=0说明没学过，随便发一个小增量
            current = 1.0
        
        payload = {
            "itemId": video.item_id,
            "teachingClassId": self.teaching_class_id,
            "teachingCourseId": self.teaching_course_id,
            "userSsoId": self.user_sso_id,
            "videoMilSeconds": video.total_milliseconds,
            "startPosition": current,
            "endPosition": current,  # 模拟播放了3秒
            "playPosition": current,
            "playbackRate": 1,
            "recordCount": 1,  # 随便一个合理的值
            "platform": "web"
        }
        
        endpoint = "/api/learning-service/admin/studentLearning/videoLearnProcessReport"
        response = self._post(endpoint, payload)
        
        if response.get('code') == 200:
            logger.info(f"   ✅ 旧视频已切换: {video.title} ({current:.0f}s → {current+3:.0f}s)")
        else:
            logger.warning(f"   ⚠️ 切换旧视频失败: {response.get('msg')}")