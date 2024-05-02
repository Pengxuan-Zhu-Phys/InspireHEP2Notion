#!/usr/bin/env python3 

import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.safari.options import Options
from bs4 import BeautifulSoup
from notion_client import Client
import time
import textwrap

class InspireHEPParser:
    def __init__(self, config_path):
        with open(config_path, 'r') as f:
            self.config = json.load(f)
        self.notion = Client(auth=self.config['secret'])
        self.driver = None

    def setup_driver(self):
        options = Options()
        options.add_argument('--headless')
        return webdriver.Safari(options=options)

    def fetch_items(self):
        return self.notion.databases.query(database_id=self.config['database_id'])['results']

    def parse_inspire_hep(self, url):
        info = {}
        self.driver = self.setup_driver()
        self.driver.get(url)
        self.driver.implicitly_wait(10)
        html = self.driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        
        info['title'] = self.get_title(soup=soup)
        info['authors'] = self.get_authors(soup=soup)
        info["keywords"] = self.get_keywords(soup=soup)
        info.update(self.get_inlines(soup=soup))
        info['abstract'] = self.get_abstract(soup=soup)
        info.update(self.get_citation(soup=soup))
        
        self.driver.quit()
        return info

    def get_title(self, soup):
        title_element = soup.find('span', {'data-test-id': 'literature-detail-title'})
        if title_element:
            title = title_element.get_text(strip=True)
        else:
            title = ''
        return title

    def get_authors(self, soup):
        authors_list_div = soup.find('div', class_='__InlineList__ di')
        if authors_list_div:
            authors_elements = authors_list_div.find_all('a', {'data-test-id': 'author-link'})
            authors = [{'name': elem.get_text(strip=True), 'link': 'https://inspirehep.net' + elem['href']} for elem in authors_elements]
        else:
            authors = []
        return authors

    def get_keywords(self, soup):
        keywords_elements = soup.find_all('span', class_='ant-tag ant-tag-blue __UnclickableTag__')
        keywords = [keyword.get_text(strip=True) for keyword in keywords_elements]
        return keywords

    def get_inlines(self, soup):
        info = {}
        pa2_div = soup.find(lambda tag: tag.name == "div" and tag.get("class") == ["pa2"] and tag.find(attrs={"data-test-id": "literature-detail-title"}))

        inlineList_div = pa2_div.find_all("div", class_="__InlineList__")
        for inline_div in inlineList_div:
            if "e-Print" in inline_div.get_text():
                eprint_div = inline_div
                eprint_link = eprint_div.find_next('a', href=True)
                eprint_url = eprint_link['href'] if eprint_link['href'].startswith('http') else f"http:{eprint_link['href']}"
                eprint_text = eprint_link.text.strip()

                eprint_category_span = eprint_link.find_next_sibling('span')
                eprint_category = eprint_category_span.text.strip() if eprint_category_span else ""
                print(f"e-Print text: {eprint_text}")
                print(f"e-Print URL: {eprint_url}")
                print(f"e-Print category: {eprint_category}")
                info["eprint"]=   {
                    "code": eprint_text,
                    "cate": eprint_category,
                    "url": eprint_url
                }
                info["page_title"] = f"arXiv: {eprint_text} {eprint_category}"
            elif "Published in" in inline_div.get_text():
                pubdiv = inline_div
                pubin = pubdiv.get_text()
                pubin = pubin.replace("Published in:", "")
                print("Published in -> ", pubin)
                info['pubin'] = pubin
            elif "Published" in inline_div.get_text() and "in" not in inline_div.get_text():
                yeardiv = inline_div
                year = yeardiv.get_text()
                year = year.replace("Published:","").strip()
                year = year.split(",")[-1].strip()
                print("Published ->", year)
                info['year'] = year
            elif "DOI" in inline_div.get_text():
                doidiv = inline_div
                doi_link = doidiv.find_next('a', href=True)
                doi_url = doi_link['href'] if doi_link['href'].startswith('http') else f"http:{doi_link['href']}"
                doi_text = doi_link.text.strip()
                print(f"DOI text: {doi_text}")
                print(f"DOI URL: {doi_url}")
                info['doi'] = {
                    "text": doi_text,
                    "url": doi_url
                }
        return info

    def get_abstract(self, soup):
        pa2_divs = soup.find_all('div', class_='pa2')
        abstract_div = None
        for div in pa2_divs:
            if "Abstract:" in div.get_text():
                abstract_div = div
                break
        if abstract_div:
            latex_elements = abstract_div.find_all('span', class_='__Latex__')
            abstract_parts = []
            for latex_element in latex_elements:
                full_text = latex_element.get_text()
                katex_elements = latex_element.find_all('span', class_='katex')
                for katex in katex_elements:
                    abstract_parts = katex.get_text(strip=True)
                    annotation = katex.find('annotation')
                    if annotation:
                        # 提取 LaTeX 文本
                        latex_formula = annotation.get_text(strip=True)
                        full_text = full_text.replace(abstract_parts, f"${latex_formula}$")
        return full_text

    def get_citation(self, soup):
        info = {}
        try:
            cite_button = self.driver.find_element(By.XPATH, "//button[contains(.,'cite')]")
            cite_button.click()
            time.sleep(2)
            modal_element = self.driver.find_element(By.CSS_SELECTOR, "div.ant-modal-content")
            modal_html = modal_element.get_attribute('innerHTML')
            soup = BeautifulSoup(modal_html, 'html.parser')
            div = soup.find("div", class_="ant-row")
            cite = div.get_text(strip=True)
            ctcode = cite.split(",")[0]
            ctcode = ctcode.split("{")[-1]
            info['citation'] = div.get_text(strip=True)
            info['citecode'] = ctcode
            return info
        except:
            return {}
    
    def update_notion(self, page_id, data):
        emoji = "📚"
        self.notion.pages.update(
            page_id=page_id,
            icon={
                "type": "emoji",
                "emoji": emoji
            },
            properties={
                'Title':        {'rich_text': [{'text': {'content': data["title"]}}]},
                "Authors":      {"rich_text": self.make_author_rich_text(data)},
                "Key Words":    {"multi_select": self.make_keywords_data(data)},
                "Processed":    {"checkbox": True}
            }
        )
        if "pubin" in data:
            self.notion.pages.update(
                page_id=page_id,
                properties={
                    "Published in": {
                        "rich_text": self.make_pubin_data(data)
                    }
                }
            )
        if "citation"in data:
            self.notion.pages.update(
                page_id=page_id,
                properties={
                    "Bibtex": {
                        "rich_text": self.make_citation_data(data)
                    }
                }
            )
        if "year" in data:
            self.notion.pages.update(
                page_id=page_id,
                properties={
                    "Year": {
                        "number": int(data['year'])
                    }
                }
            )  
        if "eprint" in data:
            self.notion.pages.update(
                page_id=page_id,
                properties={
                    "ePrint": {
                        "rich_text": self.make_eprint_data(data)
                    },
                    "Name": {  # 确保这里使用的是你的Notion数据库中的标题属性名称
                        "title": [
                            {
                                "type": "text",
                                "text": {
                                    "content": data['page_title']
                                }
                            }
                        ]
                    }
                }
            )
        if "doi" in data:
            self.notion.pages.update(
                page_id=page_id,
                properties={
                    "DOI": {
                        "rich_text": self.make_doi_data(data)
                    }
                }
            ) 
        
        blocks = self.notion.blocks.children.list(block_id=page_id)["results"]
        for block in blocks:
            self.notion.blocks.delete(block["id"])  
            
        self.notion.blocks.children.append(
            block_id=page_id, 
            children=[
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {"content": "Abstract"}
                        }
                    ]
                }
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": data['abstract']}}]}
            }]                         
        )


    def make_author_rich_text(self, info):
        authors_rich_text = []
        for i, author in enumerate(info['authors']):
            authors_rich_text.append({
                "type": "text",
                "text": {
                    "content": "• ",
                }
            })
            authors_rich_text.append({
                "type": "text",
                "text": {
                    "content": author['name'],
                    "link": {
                        "url": author['link']
                    }
                }
            })
            if i < len(info['authors']) - 1:
                authors_rich_text.append({
                    "type": "text",
                    "text": {
                        "content": "\n",
                    }
                })
        return authors_rich_text

    def make_keywords_data(self, info):
        keywords_data = [{"name": keyword} for keyword in info["keywords"]]
        return keywords_data

    def make_pubin_data(self, info):
        pubin_data = [
            {
                "type": "text",
                "text": {
                    "content": info['pubin'].strip()
                }
            }
        ]
        return pubin_data

    def make_citation_data(self, info):
        citation_data = [
            {
                "type": "text",
                "text": {
                    "content": info['citation'].strip()
                }
            }
        ]
        return citation_data

    def make_eprint_data(self, info):
        eprint_data = [
            {
                "type": "text",
                "text": {
                    "content": "• ",
                    }
            },
            {
                "type": "text",
                "text": {
                    "content": info['eprint']["code"],
                    "link": {
                        "url": info['eprint']['url']
                    }
                }
            },
            {
                "type": "text",
                "text": {
                    "content": f"-{info['eprint']['cate']}"
                }
            }
        ]
        return eprint_data

    def make_doi_data(self, info):
        doi_data = [
            {
                "type": "text",
                "text": {
                    "content": info['doi']["text"],
                    "link": {
                        "url": info['doi']['url']
                    }
                }
            }
        ]
        return doi_data

    def run(self):
        items = self.fetch_items()
        for item in items:
            if not item['properties'].get('Processed', {}).get('checkbox', False):
                url = item['properties']['Links']['url']
                info = self.parse_inspire_hep(url)
                self.update_notion(item['id'], info)

if __name__ == "__main__":
    parser = InspireHEPParser('notion_info.json')
    parser.run()
