from ontologyag.graphdb_service import GraphDBService
import logging


def test_create_repo(repo_name, gdb):
    try:
        print(f"正在创建仓库 {repo_name}...")
        gdb.create_repository(repo_name, overwrite=True)
        print(f"仓库 {repo_name} 创建成功")
    except Exception as e:
        logging.error(f"仓库创建失败: {str(e)}")
        raise


def test_insert_triple(triples: list, repo_name: str, gdb):
    gdb.insert_triples(triples, repo_name)


def test_upload_udf(file_path: str, repo_name:str, gdb):
    try:
        gdb.upload_rdf(
            file_path,
            rdf_format="rdfxml",
            repository=repo_name
        )
        print(f"本体文件上传成功")
    except Exception as e:
        logging.error(f"上传失败: {str(e)}")


def test_query(query_sparql:str, repo_name:str, gdb):
    try:
        query_result = gdb.query(query_sparql, repository=repo_name)
        print("查询结果:")
        print(query_result)
        # for result in query_result["results"]["bindings"]:
        #     print(f"{result['s']['value']} {result['p']['value']} {result['o']['value']}")
    except Exception as e:
        logging.error(f"查询失败: {str(e)}")



if __name__ == "__main__":

    repo_name = "wind-solar"

    # 初始化服务（无需参数）
    gdb = GraphDBService()

    # 测试创建仓库
    test_create_repo(repo_name, gdb)

    # 测试本体文件上传
    test_upload_udf("./ontology.owl", repo_name, gdb)

    # 测试插入三元组
    triples = [
        ("tyqy:Laowang", "rdf:type", "tyqy:BigLao"),
        ("tyqy:Laowang", "tyqy:name", '"Gebi Laowang"')
    ]
    test_insert_triple(triples, repo_name, gdb)

    # 测试sparql查询
    query_sparql = '''
    SELECT * WHERE {
    tyqy:Laowang ?p ?o .  
    } 
    LIMIT 100
    '''
    test_query(query_sparql, repo_name, gdb)

    test_upload_udf("./ontology_update.owl", repo_name, gdb)
