"""
course_fetcher.py - 课程列表获取模块
自动获取用户的课程、章节、视频信息，交互式选择
"""

import json
import logging
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin
import requests

logger = logging.getLogger(__name__)


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
        out.extend(_extract_videos(child))
    if out:
        return out
    if node.get('totalTime'):
        return [node]
    return []


class CourseInfo:
    """课程信息"""
    def __init__(self, data: Dict):
        self.course_id = data.get('courseId', '')
        self.course_name = data.get('courseName', '')
        self.class_id = data.get('classId', '')
        self.class_name = data.get('className', '')
        self.teacher_name = data.get('teacherName', '')
        self.semester = data.get('semester', '')
        self.course_status = data.get('courseStatus', 1)  # 1=学习中, 2=已完成
        self.examine_num = data.get('examineNum', '0')
        self.complete_examine_num = data.get('completeExamineNum', '0')
        self.total_score = data.get('totalScore', 0)
        self.course_resource_id = data.get('courseResourceId', '')
        self.tenant_id = data.get('tenantId', '90001')
        self.course_code = data.get('courseCode', '')
    
    @property
    def progress_percent(self) -> float:
        examine_num = int(self.examine_num) if self.examine_num else 0
        complete_num = int(self.complete_examine_num) if self.complete_examine_num else 0
        if examine_num == 0:
            return 0
        return (complete_num / examine_num) * 100
    
    @property
    def is_completed(self) -> bool:
        return self.course_status == 2
    
    def __str__(self):
        status = "✅" if self.is_completed else "📖"
        return f"{status} {self.course_name} | {self.teacher_name} | {self.class_name} | 进度: {self.progress_percent:.1f}%"


class ChapterInfo:
    """章节信息"""
    def __init__(self, data: Dict):
        self.chapter_id = data.get('id', '')
        self.title = data.get('title', '')
        self.status = data.get('status', 1)
        self.parent_id = data.get('parentId', '0')
        self.type = data.get('type', '0')  # 0=章, 1=节(视频)
        self.children: List[VideoInfo] = []
        
        for child in data.get('children', []):
            for video_data in _extract_videos(child):
                self.children.append(VideoInfo(video_data))
    
    @property
    def is_completed(self) -> bool:
        return self.status == 2
    
    @property
    def video_count(self) -> int:
        return len(self.children)
    
    @property
    def completed_count(self) -> int:
        return sum(1 for v in self.children if v.is_completed)


class VideoInfo:
    """视频信息"""
    def __init__(self, data: Dict):
        self.item_id = data.get('id', '')
        self.title = data.get('title', '')
        self.resource_id = data.get('resourceId', '')
        self.total_time = data.get('totalTime') or 0
        self.study_time = data.get('studyTime') or 0
        self.status = data.get('status', 1)
        self.rate_enum = data.get('rateEnum', '0')
    
    @property
    def is_completed(self) -> bool:
        return self.status == 2
    
    @property
    def progress_percent(self) -> float:
        if not self.total_time:
            return 0
        return (self.study_time / self.total_time) * 100


class CourseFetcher:
    """课程获取器"""
    
    BASE_URL = "https://www.beeline-ai.com"
    
    # 从流量包中提取的固定参数
    TENANT_ID = "90001"
    TEACH_MODE = ["3"]  # 3=线上课程
    
    def __init__(self, session: requests.Session):
        self.session = session
        self.courses: List[CourseInfo] = []
        self.chapters: List[ChapterInfo] = []
    
    def _post(self, endpoint: str, data: Dict) -> Dict:
        """POST请求"""
        url = urljoin(self.BASE_URL, endpoint)
        try:
            response = self.session.post(url, json=data, timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"请求失败 {endpoint}: {e}")
            return {"code": 500}
    
    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """GET请求"""
        url = urljoin(self.BASE_URL, endpoint)
        try:
            response = self.session.get(url, params=params, timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"请求失败 {endpoint}: {e}")
            return {"code": 500}
    
    def fetch_course_list(self) -> List[CourseInfo]:
        """
        获取课程列表
        接口: /api/learning-service/student/course/v1/pc/queryPcLearnCoursePage
        """
        endpoint = "/api/learning-service/student/course/v1/pc/queryPcLearnCoursePage"
        data = {
            "tenantId": self.TENANT_ID,
            "teachMode": self.TEACH_MODE
        }
        
        logger.info("📡 获取课程列表...")
        response = self._post(endpoint, data)
        
        if response.get('code') != 200:
            logger.error(f"获取课程列表失败: {response}")
            return []
        
        self.courses = []
        course_data = response.get('data', {})
        
        # 进行中的课程
        having_courses = course_data.get('havingCourseList', {})
        for semester, course_list in having_courses.items():
            for course in course_list:
                self.courses.append(CourseInfo(course))
        
        # 已完成的课程
        completed_courses = course_data.get('completedCourseList', {})
        for semester, course_list in completed_courses.items():
            for course in course_list:
                self.courses.append(CourseInfo(course))
        
        logger.info(f"✅ 获取到 {len(self.courses)} 门课程")
        return self.courses
    
    def fetch_chapters(self, class_id: str) -> List[ChapterInfo]:
        """
        获取课程章节和视频
        接口: /api/learning-service/admin/studentLearning/getChapterData
        """
        endpoint = "/api/learning-service/admin/studentLearning/getChapterData"
        data = {"teachingClassId": class_id}
        
        logger.info(f"📡 获取章节数据 (classId: {class_id})...")
        response = self._post(endpoint, data)
        
        if response.get('code') != 200:
            logger.error(f"获取章节失败: {response}")
            return []
        
        self.chapters = []
        for chapter_data in response.get('data', []):
            self.chapters.append(ChapterInfo(chapter_data))
        
        total_videos = sum(len(c.children) for c in self.chapters)
        logger.info(f"✅ 获取到 {len(self.chapters)} 章, {total_videos} 个视频")
        return self.chapters
    
    def get_user_sso_id(self) -> Optional[str]:
        """从session中获取userSsoId"""
        # 尝试从Cookie或响应中获取
        for cookie in self.session.cookies:
            if 'sso' in cookie.name.lower() or 'user' in cookie.name.lower():
                logger.info(f"找到可能的SSO Cookie: {cookie.name}")
        
        # 有些接口会返回userSsoId
        return None
    
    def show_courses(self) -> List[CourseInfo]:
        """显示课程列表并返回"""
        if not self.courses:
            self.fetch_course_list()
        
        print(f"\n{'='*70}")
        print(f"📚 课程列表 (共 {len(self.courses)} 门)")
        print(f"{'='*70}")
        
        active_courses = []
        completed_courses = []
        
        for course in self.courses:
            if course.is_completed:
                completed_courses.append(course)
            else:
                active_courses.append(course)
        
        # 显示进行中的课程
        if active_courses:
            print(f"\n📖 进行中的课程 ({len(active_courses)} 门):")
            print(f"{'-'*70}")
            for i, course in enumerate(active_courses, 1):
                print(f"[{i}] {course}")
        
        # 显示已完成的课程
        if completed_courses:
            print(f"\n✅ 已完成的课程 ({len(completed_courses)} 门):")
            print(f"{'-'*70}")
            for i, course in enumerate(completed_courses, len(active_courses) + 1):
                print(f"[{i}] {course}")
        
        print(f"{'='*70}")
        return self.courses
    
    def show_chapters(self, course: CourseInfo) -> Tuple[str, str, str, List[ChapterInfo]]:
        """
        显示课程章节并返回关键信息
        
        Returns:
            (class_id, course_id, user_sso_id, chapters)
        """
        chapters = self.fetch_chapters(course.class_id)
        
        if not chapters:
            print("❌ 未获取到章节信息")
            return course.class_id, course.course_id, "", []
        
        print(f"\n{'='*70}")
        print(f"📖 {course.course_name}")
        print(f"👨‍🏫 教师: {course.teacher_name} | 班级: {course.class_name}")
        print(f"📊 总体进度: {course.progress_percent:.1f}%")
        print(f"{'='*70}")
        
        total_videos = 0
        completed_videos = 0
        
        for chapter in chapters:
            print(f"\n📂 {chapter.title} {'✅' if chapter.is_completed else ''}")
            
            for video in chapter.children:
                total_videos += 1
                if video.is_completed:
                    completed_videos += 1
                print(f"  {video}")
        
        print(f"\n{'='*70}")
        print(f"视频完成: {completed_videos}/{total_videos}")
        print(f"{'='*70}")
        
        # userSsoId 需要从别处获取，先返回空
        return course.class_id, course.course_id, "", chapters
    
    def interactive_select_course(self) -> Optional[Tuple[str, str, str]]:
        """交互式选择课程，返回 (class_id, course_id, user_sso_id)"""
        # 1. 显示课程列表
        self.show_courses()
        
        # 2. 选择课程
        try:
            choice = input(f"\n请选择课程编号 (1-{len(self.courses)}, 输入q退出): ").strip()
            
            if choice.lower() == 'q':
                print("👋 退出系统")
                return None
            
            idx = int(choice) - 1
            
            if idx < 0 or idx >= len(self.courses):
                print("❌ 无效选择")
                return None
            
            selected_course = self.courses[idx]
            print(f"\n✅ 已选择: {selected_course.course_name}")
            
        except (ValueError, IndexError):
            print("❌ 请输入有效数字")
            return None
        
        # 3. 显示章节确认
        class_id, course_id, sso_id, chapters = self.show_chapters(selected_course)
        
        if not chapters:
            return None
        
        # 4. 确认
        confirm = input(f"\n确认选择此课程? (y/n): ").strip().lower()
        if confirm != 'y':
            return None
        
        return class_id, course_id, sso_id