import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
const files=['land.json','populated-places.source.json','rivers.source.json','terrain.source.json'];
const catalog=files.map(file=>({id:file,file:`data/${file}`,url:`https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/${({'land.json':'ne_50m_land.geojson','populated-places.source.json':'ne_10m_populated_places.geojson','rivers.source.json':'ne_50m_rivers_lake_centerlines.geojson','terrain.source.json':'ne_10m_geography_regions_polys.geojson'})[file]}`,retrieved:'2026-10-20',license:'Public domain',commercialUse:true,licenseUrl:'https://www.naturalearthdata.com/about/terms-of-use/',sha256:createHash('sha256').update(readFileSync(`data/${file}`)).digest('hex')}));
for(const item of catalog){const fc=JSON.parse(readFileSync(item.file,'utf8'));if(fc.type!=='FeatureCollection'||!fc.features.length)throw Error(`Invalid ${item.file}`);}
const terrainSource=JSON.parse(readFileSync('data/terrain.source.json','utf8'));
writeFileSync('data/terrain.json',JSON.stringify({...terrainSource,features:terrainSource.features.filter(f=>['Qilian Mountains','Gobi Desert','Tibetan Plateau'].includes(f.properties.NAME_EN))}));
const places=JSON.parse(readFileSync('data/places.json','utf8').replace(/^\uFEFF/,''));
const original=JSON.parse(readFileSync('data/populated-places.source.json','utf8'));
for(const p of places){const match=original.features.find(f=>f.properties.NAME===p.sourceName);if(!match||JSON.stringify(match.geometry.coordinates)!==JSON.stringify(p.coordinates))throw Error(`Unverified place ${p.name}`);}
writeFileSync('docs/sources.json',JSON.stringify({geodata:catalog,history:[{id:'unesco-1442',url:'https://whc.unesco.org/en/list/1442/',reviewed:'2026-10-20',use:'仅核查事实，中文脚本自行撰写；未使用照片、视频或逐字转载',pageDescriptionLicense:'CC-BY-SA IGO 3.0',claims:['河西走廊是长安向西通往敦煌方向路网的重要段落','路网连接贸易与文化交流；驿站与防御设施支持交通']}],limitations:['城市为现代位置参考','连线是示意，不是古代精确路线','现代河流数据不等于汉代河道','不提供历史疆域与精确战役路线']},null,2));
mkdirSync('out',{recursive:true});const db=new DatabaseSync('out/chronoatlas.sqlite');
db.exec('CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,json TEXT NOT NULL); CREATE TABLE IF NOT EXISTS places(id TEXT PRIMARY KEY,json TEXT NOT NULL); CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,json TEXT NOT NULL,updated_at TEXT NOT NULL); CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,status TEXT NOT NULL,details TEXT NOT NULL);');
for(const item of catalog)db.prepare('INSERT OR REPLACE INTO sources VALUES (?,?)').run(item.id,JSON.stringify(item));
for(const p of places)db.prepare('INSERT OR REPLACE INTO places VALUES (?,?)').run(p.sourceName,JSON.stringify(p));
db.close();console.log(`Verified ${catalog.length} GeoJSON datasets and ${places.length} source-exact city coordinates; SQLite catalog ready.`);
