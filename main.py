"""
main.py - 芯位平台自动刷课主程序
"""

import os
import json
import time
import logging
import argparse
from login import BeeLineAuth
from auto_player import AutoPlayer
from course_fetcher import CourseFetcher

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('brush_course.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

CONFIG_FILE = "config.json"


def load_config() -> dict:
    """加载配置"""
    default_config = {
        "username": "",
        "password": "",
        "teachingClassId": "",
        "teachingCourseId": "",
        "userSsoId": "",
        "report_interval": 30,
        "random_delay": True,
        "skip_completed": True,
    }
    
    env_mapping = {
        'BEELINE_USERNAME': 'username',
        'BEELINE_PASSWORD': 'password',
        'BEELINE_CLASS_ID': 'teachingClassId',
        'BEELINE_COURSE_ID': 'teachingCourseId',
        'BEELINE_SSO_ID': 'userSsoId',
    }
    
    for env_var, config_key in env_mapping.items():
        value = os.environ.get(env_var)
        if value:
            default_config[config_key] = value
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                file_config = json.load(f)
            default_config.update(file_config)
        except Exception as e:
            logger.warning(f"加载配置文件失败: {e}")
    
    return default_config


def save_config(config: dict):
    """保存配置"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    logger.info(f"💾 配置已保存: {CONFIG_FILE}")


def main():
    parser = argparse.ArgumentParser(description='芯位平台自动刷课')
    parser.add_argument('--show', action='store_true', help='仅显示课程进度')
    parser.add_argument('--list', action='store_true', help='列出所有课程')
    parser.add_argument('--interval', type=int, help='上报间隔（秒）')
    parser.add_argument('--no-random', action='store_true', help='禁用随机延迟')
    parser.add_argument('--target', nargs='+', help='指定视频标题（可多个）')
    parser.add_argument('--debug', action='store_true', help='显示详细发包日志')
    args = parser.parse_args()
    
    # 加载配置
    config = load_config()
    
    # 命令行参数覆盖
    if args.interval:
        config['report_interval'] = args.interval
    if args.no_random:
        config['random_delay'] = False
    
    # ==================== 1. 登录 ====================
    print(f"\n{'='*60}")
    print(f"交流群：1103025029")
    print(f"🔐 登录认证")
    print(f"{'='*60}")
    
    auth = BeeLineAuth()
    
    if not auth.load_session():
        username = config.get('username')
        password = config.get('password')
        
        if not username:
            username = input("用户名: ").strip()
        if not password:
            password = input("密码: ").strip()
        
        success, message = auth.login(username, password)
        if not success:
            print(f"❌ 登录失败: {message}")
            return
        
        print(f"✅ {message}")
        auth.save_session()
        config['username'] = username
        config['password'] = password  # 保存密码，避免下次重复输入
        save_config(config)
    
    print(f"✅ 认证成功")
    
    # ==================== 2. 获取课程信息 ====================
    fetcher = CourseFetcher(auth.get_session())
    
    # 如果只是列出课程
    if args.list:
        fetcher.show_courses()
        return
    
    # 检查配置中是否有课程信息
    class_id = config.get('teachingClassId', '')
    course_id = config.get('teachingCourseId', '')
    sso_id = config.get('userSsoId', '')
    
    while not class_id:
        # 交互式选择课程
        result = fetcher.interactive_select_course()
        if result:
            class_id, course_id, sso_id = result
            config['teachingClassId'] = class_id
            config['teachingCourseId'] = course_id
            config['userSsoId'] = sso_id
            save_config(config)
        else:
            # 用户取消或输入无效，直接退出，避免死循环
            print("已取消选择，程序退出")
            return
    
    
    # ==================== 3. 创建刷课客户端 ====================
    # token 被顶掉时（平台单会话），自动用配置里的账号密码重新登录
    def relogin() -> bool:
        uname = config.get('username', '')
        pwd = config.get('password', '')
        if not uname or not pwd:
            logger.error("没有保存账号密码，无法自动重新登录")
            return False
        for attempt in range(1, 4):
            ok, msg = auth.login(uname, pwd)
            if ok:
                auth.save_session()
                logger.info("✅ 已自动重新登录")
                return True
            logger.warning(f"自动重新登录失败({attempt}/3): {msg}")
            if any(k in str(msg) for k in ('频繁', '稍后', '验证码')):
                wait = 60 * attempt
                logger.info(f"等待 {wait} 秒后重试...")
                time.sleep(wait)
            else:
                break
        return False

    player = AutoPlayer(
        session=auth.get_session(),
        class_id=class_id,
        course_id=course_id,
        sso_id=sso_id,
        debug=args.debug,
        relogin=relogin,
    )
    
    # ==================== 4. 进入课程 + 显示/开始刷课 ====================
    
    # 先进入课程（切换当前学习课程）
    if not player.enter_class():
        print("❌ 进入课程失败，无法刷课")
        return
    
    if args.show:
        player.show_progress()
        return
    
    player.show_progress()
    
    target_titles = args.target
    if target_titles:
        print(f"\n🎯 指定视频: {', '.join(target_titles)}")
    
    while True:
        confirm = input(f"\n开始刷课? (y/n/q): ").strip().lower()
        if confirm == 'y':
            break
        elif confirm == 'q':
            print("已退出")
            return
        else:
            # 选n，重新选课程
            class_id = ''
            while not class_id:
                result = fetcher.interactive_select_course()
                if result:
                    class_id, course_id, sso_id = result
                    config['teachingClassId'] = class_id
                    config['teachingCourseId'] = course_id
                    config['userSsoId'] = sso_id
                    save_config(config)
                else:
                    print("已取消选择，程序退出")
                    return
            
            # 重新创建player
            player = AutoPlayer(
                session=auth.get_session(),
                class_id=class_id,
                course_id=course_id,
                sso_id=sso_id,
                debug=args.debug,
                relogin=relogin,
            )
            player.show_progress()
    
    # ==================== 5. 开始 ====================
    print(f"\n{'='*60}")
    print(f"🎬 开始刷课")
    print(f"{'='*60}")
    
    start_time = time.time()
    
    # main.py 中调用部分改为：
    stats = player.complete_all_videos(
        skip_completed=config.get('skip_completed', True),
        target_titles=target_titles
    )
    
    elapsed = time.time() - start_time
    
    # ==================== 6. 统计 ====================
    print(f"\n{'='*60}")
    print(f"📊 刷课完成统计")
    print(f"{'='*60}")
    print(f"  总视频数: {stats['total_videos']}")
    print(f"  已完成:   {stats['completed_videos']}")
    print(f"  已跳过:   {stats['skipped_videos']}")
    print(f"  失败:     {stats['failed_videos']}")
    print(f"  总耗时:   {elapsed/60:.1f} 分钟")
    print(f"{'='*60}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n⚠️ 程序被中断")
    except Exception as e:
        logger.error(f"程序异常: {e}", exc_info=True)