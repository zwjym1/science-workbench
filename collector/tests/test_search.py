import json,unittest
from dycollector.search import parse_search_html,related_words
class SearchTests(unittest.TestCase):
 def test_server_rendered_video_not_statistics_or_other_records(self):
  data={'aweme_info':{'aweme_id':'7667409251216819441','desc':'真实页面夹具','create_time':123,'statistics':{'digg_count':12,'secret':'no'}}}
  record='8:'+json.dumps(data,ensure_ascii=False)+'\n'
  html='<script>self.__rsc_f.push('+json.dumps([1,record])+')</script>'
  rows=parse_search_html(html)
  self.assertEqual(len(rows),1);self.assertEqual(rows[0]['statistics'],{'digg_count':12})
 def test_no_eval(self):
  self.assertEqual(parse_search_html('<script>dangerous()</script>'),[])
 def test_related_terminates_at_footer(self):
  self.assertEqual(related_words('大家还在搜\n宇宙\n使用前必读\n登录账号'),['宇宙'])

 def test_restriction_survives_page_close_failure(self):
  import asyncio
  from dycollector.search import search_page
  class Page:
   def on(self,*a):pass
   def remove_listener(self,*a):pass
   async def set_viewport_size(self,*a):pass
   async def goto(self,*a,**k):return type('R',(),{'status':403})()
   async def close(self):raise RuntimeError('close failed')
  class Context:
   async def new_page(self):return Page()
  result=asyncio.run(search_page(Context(),None,'科普'))
  self.assertIn('restriction',result)
