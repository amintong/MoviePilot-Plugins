from typing import List, Dict, Any
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

