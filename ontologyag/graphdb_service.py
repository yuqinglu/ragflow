import logging
import requests
from requests.auth import HTTPBasicAuth
from api import settings
from urllib.parse import urljoin

class GraphDBService:
    def __init__(self, repository: str = None):
        self.base_url = f"http://{settings.GRAPHDB_CONFIG['host']}:{settings.GRAPHDB_CONFIG['port']}"
        self.repository = repository or settings.GRAPHDB_CONFIG['repository']
        self.auth = HTTPBasicAuth(
            settings.GRAPHDB_CONFIG['user'],
            settings.GRAPHDB_CONFIG['password']
        )
        self.session = requests.Session()
        self.session.auth = self.auth
        self.session.headers.update({'Accept': 'application/sparql-results+json'})

    def create_repository(self, repo_name: str, overwrite: bool = False):
        """
        创建新的GraphDB仓库
        :param repo_name: 仓库名称
        :param overwrite: 是否覆盖已存在仓库
        """
        try:
            if overwrite:
                delete_url = urljoin(self.base_url, f"/repositories/{repo_name}")
                response = self.session.delete(delete_url)
                if response.status_code not in [204, 404]:
                    raise Exception(f"删除仓库失败: {response.text}")

            create_url = urljoin(self.base_url, "/repositories")
            put_url = urljoin(self.base_url, f"/repositories/{repo_name}")
            config_template = f"""
                @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>.
                @prefix rep: <http://www.openrdf.org/config/repository#>.
                @prefix sr: <http://www.openrdf.org/config/repository/sail#>.
                @prefix sail: <http://www.openrdf.org/config/sail#>.
                
                [] a rep:Repository ;
                    rep:repositoryID "{repo_name}" ;
                    rdfs:label "{repo_name}" ;
                    rep:repositoryImpl [
                        rep:repositoryType "graphdb:SailRepository" ;
                        sr:sailImpl [
                            sail:sailType "graphdb:Sail" 
                        ]
                    ].
                """
            response = self.session.put(
                put_url,
                headers={"Content-Type": "application/x-turtle"},
                data=config_template
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logging.error(f"仓库操作失败: {str(e)}")
            raise

    def insert_triples(self, triples: list, repository: str = None):
        try:
            repo = repository or self.repository
            update_url = urljoin(self.base_url, f"/repositories/{repo}/statements")
            
            # 将三元组转换为SPARQL INSERT DATA语句
            prefix_declaration = """PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX tyqy: <http://tyqy.com/wind-solar/0.1#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
"""
            
            triples_data = '\n'.join(
                f'{s} {p} {o}.' for (s, p, o) in triples
            )
            sparql = f"{prefix_declaration}\nINSERT DATA {{ {triples_data} }}"
            
            print(sparql)
            response = self.session.post(
                update_url,
                headers={"Content-Type": "application/sparql-update"},
                data=sparql
            )
            response.raise_for_status()
            return {'status': 'success', 'inserted': len(triples)}
        except Exception as e:
            logging.error(f"三元组插入失败: {str(e)}")
            raise

    def query(self, sparql: str, repository: str = None):
        try:
            prefix_declaration = """PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            PREFIX tyqy: <http://tyqy.com/wind-solar/0.1#>
            """

            repo = repository or self.repository
            query_url = urljoin(self.base_url, f"/repositories/{repo}")
            
            # 将图模式转换为SPARQL查询
            # s, p, o = pattern
            sparql = f"{prefix_declaration}\n{sparql}"

            print(sparql)
            response = self.session.post(
                query_url,
                headers={"Accept": "application/sparql-results+json"},
                data={"query": sparql}
            )
            response.raise_for_status()
            return response.json()['results']['bindings']
        except Exception as e:
            logging.error(f"图模式查询失败: {str(e)}")
            raise

    def upload_rdf(self, file_path: str, rdf_format: str = 'turtle', repository: str = None):
        """
        上传RDF文件到GraphDB仓库
        :param file_path: RDF文件绝对路径
        :param rdf_format: 支持格式 turtle|n3|rdfxml
        :param repository: 指定仓库名
        """
        try:
            format_mapping = {
                'turtle': 'application/x-turtle',
                'n3': 'text/n3',
                'rdfxml': 'application/rdf+xml'
            }
            repo = repository or self.repository
            content_type = format_mapping[rdf_format.lower()]

            upload_url = urljoin(self.base_url, 
                f"/repositories/{repo}/rdf-graphs/service?default")

            with open(file_path, 'rb') as f:
                response = self.session.post(
                    upload_url,
                    headers={'Content-Type': content_type},
                    data=f.read()
                )

            response.raise_for_status()
            return response.text
        except KeyError:
            raise ValueError(f"不支持的RDF格式: {rdf_format}，可用格式: {', '.join(format_mapping.keys())}")
        except requests.exceptions.HTTPError as e:
            logging.error(f"RDF文件上传失败: {e.response.text}")
            raise
        except Exception as e:
            logging.error(f"文件操作失败: {str(e)}")
            raise

    def list_repositories(self):
        try:
            response = self.session.get(
                urljoin(self.base_url, "/repositories")
            )
            return response.json()
        except Exception as e:
            logging.error(f"Repository listing failed: {str(e)}")
            raise
