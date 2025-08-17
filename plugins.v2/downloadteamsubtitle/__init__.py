import datetime
import threading
from typing import List, Tuple, Dict, Any, Optional

import pytz
from app.helper.sites import SitesHelper
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.context import Context, MediaInfo, TorrentInfo
from app.core.event import eventmanager, Event
from app.db.downloadhistory_oper import DownloadHistoryOper
from app.db.models.downloadhistory import DownloadHistory
from app.helper.downloader import DownloaderHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import ServiceInfo
from app.schemas.types import EventType, MediaType
from app.utils.string import StringUtils

from app.utils.http import RequestUtils
from app.utils.string import StringUtils
from app.utils.system import SystemUtils
from app.helper.torrent import TorrentHelper

import shutil
from pathlib import Path

from mteam import MTeamClient
from mteam.subtitle import SubtitleSearch, SubtitleLanguage


class SiteInfo:
    id: int = None
    name: str = None
    domain: str = None
    ext_domains: List[str] = None
    encoding: str = None
    parser: str = None
    public: bool = None
    schema: str = None
    search: Dict[str, Any] = None
    torrents: Dict[str, Any] = None
    url: str = None
    pri: int = None
    category: Dict[str, Any] = None
    torrent: Dict[str, Any] = None
    cookie: str = None
    ua: str = None
    apikey: str = None
    token: str = None
    proxy: bool = None
    filter: str = None
    render: int = None
    note: str = None
    limit_interval: int = None
    limit_count: int = None
    limit_seconds: int = None
    timeout: int = None
    is_active: bool = None

    def __setattr__(self, name: str, value: Any):
        self.__dict__[name] = value

    def __get_properties(self):
        """
        获取属性列表
        """
        property_names = []
        for member_name in dir(self.__class__):
            member = getattr(self.__class__, member_name)
            if isinstance(member, property):
                property_names.append(member_name)
        return property_names

    def from_dict(self, data: dict):
        """
        从字典中初始化
        """
        properties = self.__get_properties()
        for key, value in data.items():
            if key in properties:
                continue
            setattr(self, key, value)


class TeamProcess():
    LOG_TAG=None
    team_domain_flg = "team"
    team_subtitle_url = "https://api.m-team.cc/api/subtitle/dlV2?credential={credential}"
    downloadhistory_oper = None
    downloader_helper = None
    sites_helper = None 
    def __init__(self, LOG_TAG:str):
        self.LOG_TAG = LOG_TAG
        self.downloadhistory_oper = DownloadHistoryOper()
        self.downloader_helper = DownloaderHelper()
        self.sites_helper = SitesHelper()
        pass

    def get_team_siteinfo(self)->SiteInfo:
        sites = self.sites_helper.get_indexers()
        # 获取站点信息
        for site in sites:
            siteInfo = SiteInfo()
            siteInfo.from_dict(site)
            logger.info(f"{self.LOG_TAG}站点信息：{siteInfo.domain}, {siteInfo.apikey}")    
            if siteInfo.domain.find(self.team_domain_flg) >0:
                return  siteInfo
            for ext_domain in siteInfo.ext_domains:
                if ext_domain.find(self.team_domain_flg) >0:
                    return siteInfo   
        return None
    
    def is_team_site(self, torrent: TorrentInfo)->bool:
        return torrent.page_url.find(self.team_domain_flg) >0
    

    def get_team_torrentid(self, torrent: TorrentInfo)->str:
        return torrent.page_url.split("/")[-1]
    
    def get_torrent_subtitle(self, torrentid:str, apikey:str)->List[str] :
        url_list = []
         # 使用上下文管理器
        with MTeamClient(api_key=apikey) as client: 
            result = client.subtitle.get_subtitle_list(torrentid)
            logger.info(f"{self.LOG_TAG}Response code: {result.code}")
            logger.info(f"{self.LOG_TAG}Response message: {result.message}")
            
            if result.data:
                for subtitle in result.data:
                    logger.info("=" * 50)
                    logger.info(f"{self.LOG_TAG}字幕ID: {subtitle.id}")
                    result = client.subtitle.generate_download_link(subtitle.id)
                    if result.code == 0:
                        url_list.append(self.team_subtitle_url.format(credential=result.data))
                    else:
                        logger.error(f"{self.LOG_TAG}获取字幕下载链接失败: {result.message}")
        return url_list 
        
    
    def download_file(self,sublink_list:List[str], download_dir:Path)->int:
        ok_cnt = 0
        for sublink in sublink_list:
            logger.info(f"{self.LOG_TAG}找到字幕下载链接：{sublink}，开始下载...")
            # 下载
            ret = RequestUtils().get_res(sublink)
            if ret and ret.status_code == 200:
                # 保存ZIP
                file_name = TorrentHelper.get_url_filename(ret, sublink)
                if not file_name:
                    logger.warn(f"{self.LOG_TAG}链接不是字幕文件：{sublink}")
                    continue
                if file_name.lower().endswith(".zip"):
                    logger.info(f"{self.LOG_TAG}下载ZIP文件：{file_name}")
                    # ZIP包
                    zip_file = settings.TEMP_PATH / file_name
                    # 保存
                    zip_file.write_bytes(ret.content)
                    # 解压路径
                    zip_path = zip_file.with_name(zip_file.stem)
                    # 解压文件
                    shutil.unpack_archive(zip_file, zip_path, format='zip')
                    # 遍历转移文件
                    for sub_file in SystemUtils.list_files(zip_path, settings.RMT_SUBEXT):
                        target_sub_file = download_dir / sub_file.name
                        if target_sub_file.exists():
                            logger.info(f"{self.LOG_TAG}字幕文件已存在：{target_sub_file}")
                            continue
                        logger.info(f"{self.LOG_TAG}转移字幕 {sub_file} 到 {target_sub_file} ...")
                        SystemUtils.copy(sub_file, target_sub_file)
                    # 删除临时文件
                    try:
                        shutil.rmtree(zip_path)
                        zip_file.unlink()
                    except Exception as err:
                        logger.error(f"{self.LOG_TAG}删除临时文件失败：{str(err)}")
                    ok_cnt += 1
                else:
                    sub_file = settings.TEMP_PATH / file_name
                    # 保存
                    sub_file.write_bytes(ret.content)
                    target_sub_file = download_dir / sub_file.name
                    logger.info(f"{self.LOG_TAG}转移字幕 {sub_file} 到 {target_sub_file}")
                    SystemUtils.copy(sub_file, target_sub_file)
                    ok_cnt += 1
            else:
                logger.error(f"下载字幕文件失败：{sublink}")
                continue
        return ok_cnt
    
    def process_torrent(self, torrent: TorrentInfo, hash_ :str):
        if not self.is_team_site(torrent):
            logger.info(f"{self.LOG_TAG}不是馒头站点，跳过")
            return
        team_torrentid = self.get_team_torrentid(torrent)
        logger.info(f"{self.LOG_TAG}处理种子：{team_torrentid}")

        team_siteinfo = self.get_team_siteinfo()
        if not team_siteinfo:
            logger.info(f"{self.LOG_TAG}未找到馒头站点")
            return
        subtitles = self.get_torrent_subtitle(team_torrentid, team_siteinfo.apikey)
        if not subtitles:
            logger.info(f"{self.LOG_TAG}未找到字幕文件")
            return
        if len(subtitles) == 0:
            logger.info(f"{self.LOG_TAG}未找到字幕文件")
            return
        logger.info(f"{self.LOG_TAG}开始下载字幕：{subtitles}")

        history: DownloadHistory = self.downloadhistory_oper.get_by_hash(hash_)
        if not history.path:
            logger.info(f"{self.LOG_TAG}未找到下载历史")
            return
        logger.info(f"{self.LOG_TAG}下载字幕文件到：{history.path}")  
        ok_cnt = self.download_file(subtitles, Path(history.path))
        if ok_cnt== 0:
            logger.info(f"{self.LOG_TAG}下载字幕文件失败")
        total_cnt = len(subtitles)
        logger.info(f"{self.LOG_TAG}下载字幕文件成功/可用{ok_cnt}/{total_cnt}")


    def process_history(self, history: DownloadHistory):
        pass

class DownloadTeamSubtitle(_PluginBase):
    # 插件名称
    plugin_name = "下载任务字幕"
    # 插件描述
    plugin_desc = "自动给下载任务添加字幕"
    # 插件图标
    plugin_icon = "Youtube-dl_B.png"
    # 插件版本
    plugin_version = "0.2"
    # 插件作者
    plugin_author = "小明"
    # 作者主页
    author_url = "https://github.com/amintong"
    # 插件配置项ID前缀
    plugin_config_prefix = "DownloadTeamSubtitle_"
    # 加载顺序
    plugin_order = 2
    # 可使用的用户级别
    auth_level = 1
    # 日志前缀
    LOG_TAG = "[DownloadTeamSubtitle] "

    # 退出事件
    _event = threading.Event()
    # 私有属性
    downloadhistory_oper = None
    sites_helper = None
    downloader_helper = None
    team_process = None

    _scheduler = None
    _enabled = False
    _onlyonce = False
    _interval = "计划任务"
    _interval_cron = "5 4 * * *"
    _interval_time = 6
    _interval_unit = "小时"
    _enabled_media_tag = False
    _enabled_tag = True
    _enabled_category = False
    _category_movie = None
    _category_tv = None
    _category_anime = None
    _downloaders = None

    def init_plugin(self, config: dict = None):
        self.downloadhistory_oper = DownloadHistoryOper()
        self.downloader_helper = DownloaderHelper()
        self.sites_helper = SitesHelper()
        self.team_process = TeamProcess(self.LOG_TAG)

        siteInfo = self.team_process.get_team_siteinfo() 
        if siteInfo:
            logger.info(f"{self.LOG_TAG}找到站点: {siteInfo.domain}")
        else:
            logger.error(f"{self.LOG_TAG}未找到馒头站点")
            return  

        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._interval = config.get("interval") or "计划任务"
            self._interval_cron = config.get("interval_cron") or "5 4 * * *"
            self._interval_time = self.str_to_number(config.get("interval_time"), 6)
            self._interval_unit = config.get("interval_unit") or "小时"
            self._enabled_media_tag = config.get("enabled_media_tag")
            self._enabled_tag = config.get("enabled_tag")
            self._enabled_category = config.get("enabled_category")
            self._category_movie = config.get("category_movie") or "电影"
            self._category_tv = config.get("category_tv") or "电视"
            self._category_anime = config.get("category_anime") or "动漫"
            self._downloaders = config.get("downloaders")

        # 停止现有任务
        self.stop_service()

        if self._onlyonce:
            # 创建定时任务控制器
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            # 执行一次, 关闭onlyonce
            self._onlyonce = False
            config.update({"onlyonce": self._onlyonce})
            self.update_config(config)
            # 添加 补全下载历史的标签与分类 任务
            self._scheduler.add_job(func=self._complemented_history, trigger='date',
                                    run_date=datetime.datetime.now(
                                        tz=pytz.timezone(settings.TZ)) + datetime.timedelta(seconds=3)
                                    )

            if self._scheduler and self._scheduler.get_jobs():
                # 启动服务
                self._scheduler.print_jobs()
                self._scheduler.start()


    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass
    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        [{
            "id": "服务ID",
            "name": "服务名称",
            "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
            "func": self.xxx,
            "kwargs": {} # 定时器参数
        }]
        """
        return []

    @staticmethod
    def str_to_number(s: str, i: int) -> int:
        try:
            return int(s)
        except ValueError:
            return i

    def _complemented_history(self):
        """
        补全下载历史的标签与分类
        """
        logger.info(f"{self.LOG_TAG}开始执行 ...")
        logger.info(f"{self.LOG_TAG}执行完成")

    
    @eventmanager.register(EventType.DownloadAdded)
    def download_added(self, event: Event):
        """
        添加下载事件
        """
        
        if not self.get_state():
            return

        if not event.event_data:
            return
            
        try:
            context: Context = event.event_data.get("context")
            _hash = event.event_data.get("hash")
            _torrent:TorrentInfo = context.torrent_info
            _media:MediaInfo = context.media_info 
            logger.info(f"{self.LOG_TAG}下载任务字幕: {_torrent.site_name}")
            self.team_process.process_torrent(_torrent, _hash)
        except Exception as e:
            logger.error(
                f"{self.LOG_TAG}分析下载事件时发生了错误: {str(e)}")

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VCheckboxBtn',
                                        'props': {
                                            'model': 'enabled_tag',
                                            'label': '自动站点标签',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VCheckboxBtn',
                                        'props': {
                                            'model': 'enabled_media_tag',
                                            'label': '自动剧名标签',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VCheckboxBtn',
                                        'props': {
                                            'model': 'enabled_category',
                                            'label': '自动设置分类',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VCheckboxBtn',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '补全下载历史的标签与分类(一次性任务)'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': True,
                                            'chips': True,
                                            'clearable': True,
                                            'model': 'downloaders',
                                            'label': '下载器',
                                            'items': [{"title": config.name, "value": config.name}
                                                      for config in self.downloader_helper.get_configs().values()]
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'interval',
                                            'label': '定时任务',
                                            'items': [
                                                {'title': '禁用', 'value': '禁用'},
                                                {'title': '计划任务', 'value': '计划任务'},
                                                {'title': '固定间隔', 'value': '固定间隔'}
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3,
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'interval_cron',
                                            'label': '计划任务设置',
                                            'placeholder': '5 4 * * *'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 6,
                                    'md': 3,
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'interval_time',
                                            'label': '固定间隔设置, 间隔每',
                                            'placeholder': '6'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 6,
                                    'md': 3,
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'interval_unit',
                                            'label': '单位',
                                            'items': [
                                                {'title': '小时', 'value': '小时'},
                                                {'title': '分钟', 'value': '分钟'}
                                            ]
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'category_movie',
                                            'label': '电影分类名称(默认: 电影)',
                                            'placeholder': '电影'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'category_tv',
                                            'label': '电视分类名称(默认: 电视)',
                                            'placeholder': '电视'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'category_anime',
                                            'label': '动漫分类名称(默认: 动漫)',
                                            'placeholder': '动漫'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '定时任务：支持两种定时方式，主要针对辅种刷流等种子补全站点信息。如没有对应的需求建议切换为禁用。'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "enabled_tag": True,
            "enabled_media_tag": False,
            "enabled_category": False,
            "category_movie": "电影",
            "category_tv": "电视",
            "category_anime": "动漫",
            "interval": "计划任务",
            "interval_cron": "5 4 * * *",
            "interval_time": "6",
            "interval_unit": "小时"
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        停止服务
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._event.set()
                    self._scheduler.shutdown()
                    self._event.clear()
                self._scheduler = None
        except Exception as e:
            print(str(e))


