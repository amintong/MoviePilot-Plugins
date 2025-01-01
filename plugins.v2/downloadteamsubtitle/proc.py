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

from .siteinfo import SiteInfo

class TeamProcess():
    LOG_TAG=None
    team_domain_flg = "team"
    downloadhistory_oper = None
    downloader_helper = None
    sites_helper = None 
    def __init__(self, LOG_TAG:str):
        self.LOG_TAG = LOG_TAG
        self.downloadhistory_oper = DownloadHistoryOper()
        self.downloader_helper = DownloaderHelper()
        self.sites_helper = SitesHelper()
        pass

    def get_team_siteinfo(self)->Tuple[bool, SiteInfo]:
        sites = self.sites_helper.get_indexers()
        # 获取站点信息
        for site in sites:
            siteInfo = SiteInfo()
            siteInfo.from_dict(site)
            logger.info(f"{self.LOG_TAG}站点信息：{siteInfo.domain}, {",".join(siteInfo.ext_domains)}")    
            if siteInfo.domain.find(self.team_domain_flg) >0:
                return True, siteInfo
            for ext_domain in siteInfo.ext_domains:
                if ext_domain.find(self.team_domain_flg) >0:
                    return True, siteInfo   
        return False, None
    
    def is_team_site(self, torrent: TorrentInfo)->bool:
        findSiteInfo, siteInfo = self.get_team_siteinfo(torrent.site_name)
        if findSiteInfo:
            return torrent.site == siteInfo.id
        return False
    
    def process_torrent(self, torrent: TorrentInfo):
        pass

    def process_history(self, history: DownloadHistory):
        pass
