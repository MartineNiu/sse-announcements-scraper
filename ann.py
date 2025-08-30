import requests
import json
import os
import re
import time
import argparse
from datetime import datetime, timedelta

# Selenium Imports
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# --- 新增根目录 & 默认值 ---
DOWNLOAD_DIR = "downloads" # 所有下载内容的根目录
DEFAULT_SECURITY_CODE = "600036"

def get_default_start_date():
    """返回三年前的今天"""
    return (datetime.now() - timedelta(days=3*365)).strftime('%Y-%m-%d')

def get_default_end_date():
    """返回今天的日期"""
    return datetime.now().strftime('%Y-%m-%d')

def clean_filename(filename):
    """
    移除文件名中的非法字符，使其可以安全地用于创建文件。
    """
    return re.sub(r'[\\/*?:"<>|]', "", filename)

def generate_yearly_date_ranges(start_date_str, end_date_str):
    """
    根据起始和结束日期，生成按自然年切分的时间段列表。
    """
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
    
    ranges = []
    current_start = start_date
    
    while current_start <= end_date:
        year_end = datetime(current_start.year, 12, 31)
        current_end = min(year_end, end_date)
        
        ranges.append(
            (current_start.strftime("%Y-%m-%d"), current_end.strftime("%Y-%m-%d"))
        )
        
        # 下一个时间段的开始是当前年底的后一天
        current_start = year_end + timedelta(days=1)
        
    return ranges

def fetch_all_announcements_paginated(session, security_code, start_date, end_date, title=""):
    """
    通过循环翻页，从上交所API获取指定范围内的所有公告。
    """
    all_announcements = []
    page_num = 1
    
    while True:
        # print(f"正在获取第 {page_num} 页的公告...")
        
        # 升级为使用params字典，更安全地处理参数
        base_url = "https://query.sse.com.cn/security/stock/queryCompanyBulletinNew.do"
        params = {
            'isPagination': 'true',
            'pageHelp.pageSize': 100,
            'pageHelp.cacheSize': 1,
            'START_DATE': start_date,
            'END_DATE': end_date,
            'SECURITY_CODE': security_code,
            'pageHelp.beginPage': page_num,
            'pageHelp.pageNo': page_num,
            'TITLE': title
        }
        
        try:
            response = session.get(base_url, params=params, timeout=15)
            response.raise_for_status()
            
            try:
                data = response.json()
            except json.JSONDecodeError:
                print(f"错误: 无法解析第 {page_num} 页的JSON响应。跳过此页。")
                page_num += 1
                continue

            current_page_data = data.get('pageHelp', {}).get('data', [])
            
            if not current_page_data:
                # print(f"第 {page_num} 页没有数据，已到达末尾。")
                break

            announcements_on_page = []
            for inner_list in current_page_data:
                for item in inner_list:
                    title = item.get("TITLE")
                    url_path = item.get("URL")
                    if title and url_path:
                        full_url = f"https://static.sse.com.cn{url_path}"
                        announcements_on_page.append({"title": title, "url": full_url})
            
            all_announcements.extend(announcements_on_page)
            
            page_num += 1
            time.sleep(0.5)

        except requests.exceptions.RequestException as e:
            print(f"请求第 {page_num} 页时发生错误: {e}。稍后重试...")
            time.sleep(2)

    return all_announcements

def download_pdf_hybrid(driver, url, filepath):
    """
    严格参照 test_selenium_download.py 的逻辑进行下载。
    """
    try:
        # 1. Selenium导航到URL以建立有效会话
        driver.get(url)
        # 2. 关键：给予足够长的等待时间让所有JS和重定向完成
        time.sleep(0)

        # 3. 从浏览器提取Cookie
        cookies = driver.get_cookies()
        if not cookies:
            raise Exception("无法从浏览器获取Cookie，下载可能被拦截。")

        # 4. 创建一个全新的requests会话并应用Cookie
        session = requests.Session()
        for cookie in cookies:
            session.cookies.set(cookie['name'], cookie['value'])
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': 'https://www.sse.com.cn/'
        }
        
        # 5. 使用配置好的requests会话下载文件
        response = session.get(url, headers=headers, stream=True, timeout=60)
        response.raise_for_status()

        # 6. 直接保存文件
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        return f"成功下载: {os.path.basename(filepath)}"

    except Exception as e:
        return f"下载失败: {os.path.basename(filepath)}, 原因: {e}"

def batch_download_sequential(driver, announcements, target_dir):
    """
    序贯下载所有公告文件。
    """
    if not announcements:
        print("没有可下载的公告。")
        return

    os.makedirs(target_dir, exist_ok=True)
    print(f"文件将被保存到: {os.path.abspath(target_dir)}")

    total = len(announcements)
    for i, ann in enumerate(announcements):
        print(f"\n[{i+1}/{total}] 正在处理: {ann['title']}")
        filepath = os.path.join(target_dir, f"{clean_filename(ann['title'])}.pdf")
        
        result = download_pdf_hybrid(driver, ann['url'], filepath)
        print(result)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="上交所公告爬虫工具")
    parser.add_argument("security_code", nargs='?', default=DEFAULT_SECURITY_CODE, help="要查询的证券代码 (默认: 600036)")
    parser.add_argument("--start", default=get_default_start_date(), help="开始日期 (YYYY-MM-DD)，默认为三年前的今天")
    parser.add_argument("--end", default=get_default_end_date(), help="结束日期 (YYYY-MM-DD)，默认为今天")
    parser.add_argument("--output", default=None, help="指定输出文件夹的名称 (默认: [证券代码]_[时间戳])")
    parser.add_argument("--title", default="", help="按公告标题关键字进行过滤 (可选)")
    
    args = parser.parse_args()
    
    SECURITY_CODE = args.security_code
    START_DATE = args.start
    END_DATE = args.end
    TITLE = args.title
    
    # 根据参数构建输出目录
    if args.output:
        target_dir = os.path.join(DOWNLOAD_DIR, args.output)
    else:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        target_dir = os.path.join(DOWNLOAD_DIR, f"{SECURITY_CODE}_{timestamp}")

    print(f"--- 任务参数 ---")
    print(f"证券代码: {SECURITY_CODE}")
    print(f"时间范围: {START_DATE} to {END_DATE}")
    if TITLE:
        print(f"标题关键字: {TITLE}")
    print(f"输出目录: {os.path.abspath(target_dir)}")
    print(f"-----------------")

    print("\n--- 初始化Selenium以绕过反爬虫 ---")
    chrome_options = Options()
    
    # 使用有头模式
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")

    driver = None
    try:
        driver = webdriver.Chrome(options=chrome_options)

        print("浏览器正在访问上交所网站以获取初始会话...")
        driver.get("https://www.sse.com.cn/disclosure/listedinfo/announcement/")
        time.sleep(5)

        cookies = driver.get_cookies()
        if not cookies:
            raise Exception("无法从浏览器获取到任何初始Cookie。")
        
        print(f"成功获取 {len(cookies)} 个初始Cookie，准备获取公告列表...")

        requests_session = requests.Session()
        for cookie in cookies:
            requests_session.cookies.set(cookie['name'], cookie['value'])
        
        requests_session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': 'https://www.sse.com.cn/'
        })

        # 1. 生成年度时间范围
        date_ranges = generate_yearly_date_ranges(START_DATE, END_DATE)
        print(f"\n时间范围已按年份拆分为 {len(date_ranges)} 个时间段: {date_ranges}")
        
        # 2. 逐个时间段获取完整的公告列表
        full_ann_list = []
        for start, end in date_ranges:
            print(f"\n--- 正在处理时间段: {start} to {end} ---")
            ann_list_for_range = fetch_all_announcements_paginated(requests_session, SECURITY_CODE, start, end, TITLE)
            full_ann_list.extend(ann_list_for_range)
            print(f"--- 时间段 {start} to {end} 处理完毕，获取到 {len(ann_list_for_range)} 条公告 ---")
        
        print(f"\n--- 所有公告列表获取完毕，总计 {len(full_ann_list)} 条 ---")
        
        # 3. 使用同一浏览器实例，序贯下载所有公告文件
        if full_ann_list:
            batch_download_sequential(driver, full_ann_list, target_dir)
            
        print("\n所有任务完成。")

    except Exception as e:
        print(f"程序执行过程中发生严重错误: {e}")
    finally:
        if driver:
            driver.quit()
            print("浏览器已关闭。")
