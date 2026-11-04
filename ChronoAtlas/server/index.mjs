import http from 'node:http';
import {DatabaseSync} from 'node:sqlite';
import {randomUUID} from 'node:crypto';
const db=new DatabaseSync('out/chronoatlas.sqlite');
const respond=(res,status,data)=>{res.writeHead(status,{'Content-Type':'application/json; charset=utf-8'});res.end(JSON.stringify(data));};
const server=http.createServer(async(req,res)=>{
 try{
 const url=new URL(req.url,'http://127.0.0.1');
 if(req.method==='GET'&&url.pathname==='/api/health')return respond(res,200,{status:'ok',ai:'not-configured',renderQueue:'CLI-only'});
 if(req.method==='GET'&&url.pathname==='/api/places')return respond(res,200,db.prepare('SELECT json FROM places').all().map(r=>JSON.parse(r.json)));
 if(req.method==='GET'&&url.pathname==='/api/sources')return respond(res,200,db.prepare('SELECT json FROM sources').all().map(r=>JSON.parse(r.json)));
 if(req.method==='GET'&&url.pathname==='/api/projects')return respond(res,200,db.prepare('SELECT id,json,updated_at FROM projects').all().map(r=>({...r,json:JSON.parse(r.json)})));
 if(req.method==='POST'&&url.pathname==='/api/projects'){
 let body='';for await(const chunk of req){body+=chunk;if(Buffer.byteLength(body)>65536)return respond(res,413,{error:'项目超过64KB'});}
 let project;try{project=JSON.parse(body);}catch{return respond(res,400,{error:'无效JSON'});}
 if(!project||typeof project.title!=='string'||project.title.length>120)return respond(res,400,{error:'需要120字以内标题'});
 const id=randomUUID();db.prepare('INSERT INTO projects VALUES (?,?,?)').run(id,JSON.stringify(project),new Date().toISOString());return respond(res,201,{id});
 }
 return respond(res,404,{error:'not-found'});
 }catch(error){console.error(error);respond(res,500,{error:'internal-error'});}
});
server.listen(4318,'127.0.0.1',()=>console.log('ChronoAtlas API http://127.0.0.1:4318'));
process.on('SIGINT',()=>server.close(()=>{db.close();process.exit(0);}));
