import duckdb

con = duckdb.connect()
con.execute("""
INSTALL httpfs;
LOAD httpfs;
SET s3_endpoint = 'minio:9000';
SET s3_access_key_id = 'lakehouse_admin';
SET s3_secret_access_key = 'minIO123';
SET s3_url_style = 'path';
SET s3_use_ssl = false;
""")

res = con.execute("""
SELECT 
    count(*) as total_comments, 
    count(distinct video_id) as total_videos,
    count(distinct place_id) as total_places,
    count(case when record_status = 'success' then 1 end) as success_records,
    count(case when record_status = 'quarantine' then 1 end) as quarantine_records
FROM read_json('s3://lakehouse/bronze/youtube/comments/crawl_date=*/*.jsonl', 
               format='newline_delimited', 
               union_by_name=true, 
               hive_partitioning=true);
""").fetchall()

print("DUCKDB S3 BRONZE QUERY RESULT:")
print("total_comments, total_videos, total_places, success_records, quarantine_records:")
print(res)
