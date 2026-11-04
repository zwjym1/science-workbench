import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {geoMercator, geoPath, geoGraticule} from 'd3-geo';
import type {GeoPermissibleObjects} from 'd3-geo';
import land from '../data/land.json';
import rivers from '../data/rivers.source.json';
import terrain from '../data/terrain.json';
import placesData from '../data/places.json';

export type FilmProps = {title:string; accent:string; scenes:string[]};
export const defaultFilm:FilmProps = {title:'为什么河西走廊如此重要？',accent:'#a23b2f',scenes:[
  '从中原向西，一条通道打开了更辽阔的世界。',
  '河西走廊连接中国内地与西域，是东西交通的重要通道。',
  '从兰州向西，经武威、张掖，抵达敦煌一带。',
  '交通、交流与经营边地，让这条走廊拥有超越距离的分量。'
]};
const places = placesData.map(p=>({...p,coordinates:[p.coordinates[0],p.coordinates[1]] as [number,number]})).sort((a,b)=>b.coordinates[0]-a.coordinates[0]);
const projection = geoMercator().center([98.2,38.5]).scale(3000).translate([640,355]).clipExtent([[-120,-120],[1400,840]]);
const path = geoPath(projection);
const landPath = path(land as unknown as GeoPermissibleObjects) ?? '';
const riversPath = path(rivers as unknown as GeoPermissibleObjects) ?? '';
const terrainLayers = terrain.features.filter(f=>['Qilian Mountains','Gobi Desert','Tibetan Plateau'].includes(f.properties.NAME_EN)).map(f=>({name:f.properties.NAME_EN,label:f.properties.NAME_EN==='Gobi Desert'?'戈壁':f.properties.NAME_EN==='Qilian Mountains'?'祁 连 山':'青 藏 高 原',d:path(f as unknown as GeoPermissibleObjects)??'',center:path.centroid(f as unknown as GeoPermissibleObjects)}));
const gridPath = path(geoGraticule().step([2,2])()) ?? '';
const insetProjection = geoMercator().center([104,35]).scale(155).translate([1108,318]).clipExtent([[1012,238],[1198,384]]);
const insetLandPath = geoPath(insetProjection)(land as unknown as GeoPermissibleObjects) ?? '';
const insetRoute = places.map(p=>insetProjection(p.coordinates)!).map((p,i)=>`${i?'L':'M'}${p[0]},${p[1]}`).join(' ');
const routePoints = places.map(p=>projection(p.coordinates)!);
const segmentLengths=routePoints.slice(1).map((p,i)=>Math.hypot(p[0]-routePoints[i][0],p[1]-routePoints[i][1]));
const totalLength=segmentLengths.reduce((sum,length)=>sum+length,0);
function routeHead(progress:number){let distance=progress*totalLength;let i=0;while(i<segmentLengths.length-1&&distance>segmentLengths[i]){distance-=segmentLengths[i];i++;}const a=routePoints[i],b=routePoints[i+1];const t=distance/segmentLengths[i];return {x:a[0]+(b[0]-a[0])*t,y:a[1]+(b[1]-a[1])*t,angle:Math.atan2(b[1]-a[1],b[0]-a[0])*180/Math.PI};}
const route = routePoints.map((p,i)=>`${i?'L':'M'}${p[0]},${p[1]}`).join(' ');
const serif='"Songti SC", "SimSun", "Noto Serif SC", serif';
const clamp={extrapolateLeft:'clamp',extrapolateRight:'clamp'} as const;
export const HexiFilm:React.FC<FilmProps> = ({title,accent,scenes})=>{
  const frame=useCurrentFrame(); const {fps}=useVideoConfig(); const seconds=frame/fps;
  const chapter=seconds<6?0:seconds<14?1:seconds<23?2:3;
  const chapterStart=[0,6,14,23][chapter];
  const captionOpacity=interpolate(seconds-chapterStart,[0,.7],[0,1],clamp);
  const routeProgress=interpolate(seconds,[6,23],[0,1],clamp);
  const zoom=interpolate(seconds,[0,6,14,23,30],[.55,1,1.08,1.12,1.03],clamp);
  const fade=interpolate(seconds,[0,1,29,30],[0,1,1,0],clamp);
  return <AbsoluteFill style={{background:'#211b13',fontFamily:serif,color:'#3b3022'}}>
    <AbsoluteFill style={{opacity:fade,background:'radial-gradient(ellipse at 45% 35%, #efe3c2 0%, #d5bc87 70%, #a78958 100%)'}}>
      <svg width="1280" height="720" viewBox="0 0 1280 720" style={{position:'absolute'}}>
        <defs>
          <filter id="paper"><feTurbulence baseFrequency=".35" numOctaves="1" seed="12" type="fractalNoise"/><feColorMatrix type="saturate" values="0"/><feBlend in="SourceGraphic" mode="multiply"/></filter>
          <radialGradient id="vignette"><stop offset="50%" stopColor="#4d3512" stopOpacity="0"/><stop offset="100%" stopColor="#37240d" stopOpacity=".17"/></radialGradient>
          <linearGradient id="wash" x2="0" y2="1"><stop stopColor="#e7d6ae"/><stop offset="1" stopColor="#c7af79"/></linearGradient>
          <clipPath id="inset-clip"><rect x="1013" y="238" width="185" height="145" rx="2"/></clipPath>
          <pattern id="terrain-hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(-30)"><line x1="0" y1="0" x2="0" y2="8" stroke="#715c3a" strokeWidth="1.3" opacity=".18"/></pattern>
          <marker id="arrow" markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 L1.4,3 Z" fill={accent}/></marker>
        </defs>
        <g opacity=".9" transform={`translate(640 360) scale(${zoom}) translate(-640 -360)`}>
          <path d={landPath} fill="url(#wash)" stroke="#81744e" strokeWidth="1.2"/>
          {terrainLayers.map(f=><g key={f.name}><path d={f.d} fill={f.name==='Gobi Desert'?'#b89a54':'#8b7651'} fillOpacity={f.name==='Qilian Mountains' ? .24 : .12} stroke="#8e7750" strokeOpacity=".22" strokeWidth=".7"/>{f.name!=='Gobi Desert'&&<path d={f.d} fill="url(#terrain-hatch)"/>}{f.name==='Qilian Mountains'&&<text x={f.center[0]} y={f.center[1]} textAnchor="middle" fontSize="24" fill="#5c492e" letterSpacing="5" stroke="#ddc89d" strokeWidth="3" paintOrder="stroke">{f.label}</text>}</g>)}
          <path d={gridPath} fill="none" stroke="#76674b" strokeWidth=".65" strokeDasharray="3 7" opacity=".3"/>
          <path d={riversPath} fill="none" stroke="#617c7b" strokeWidth="1.4" opacity=".6"/>
          <path d={route} fill="none" stroke="#9d7f43" strokeWidth="50" strokeLinecap="round" opacity=".12"/>
          <path d={route} fill="none" stroke={accent} strokeWidth="2" strokeDasharray="4 9" opacity=".3"/>
          <path d={route} fill="none" stroke={accent} strokeWidth="5" strokeLinecap="round" pathLength="1" strokeDasharray="1" strokeDashoffset={1-routeProgress}/>
          {routeProgress>.02&&(()=>{const {x,y,angle}=routeHead(routeProgress);return <path d="M-15,-7 L0,0 L-15,7 L-11,0 Z" fill={accent} transform={`translate(${x} ${y}) rotate(${angle})`}/>;})()}
          {places.map((p,i)=>{const xy=routePoints[i];const below=p.name==='敦煌'||p.name==='张掖';const reveal=interpolate(seconds,[3+i*2,4+i*2],[0,1],clamp);return <g key={p.name} transform={`translate(${xy[0]} ${xy[1]})`} opacity={reveal}>
            <circle r="15" fill="#e5d4af" stroke={accent} strokeWidth=".8"/>
            <path d="M-6,5 V-3 H-3 V-6 H0 V-3 H3 V-6 H6 V5 Z" fill={accent}/>
            <line y1={below?18:-18} y2={below?49:-49} stroke="#78613e" strokeWidth="1"/>
            <text y={below?78:-60} textAnchor="middle" fontSize="27" fontWeight="bold" fill="#3b3022" stroke="#e7d6b1" strokeWidth="5" paintOrder="stroke">{p.name}</text>
            <text y={below?98:-39} textAnchor="middle" fontSize="11" fill="#66583c">{p.coordinates[0].toFixed(2)}°E · {p.coordinates[1].toFixed(2)}°N</text>
          </g>;})}
        </g>
        <rect width="1280" height="720" filter="url(#paper)" opacity=".025"/>
        <rect width="1280" height="720" fill="url(#vignette)"/>
        <rect x="25" y="25" width="1230" height="670" rx="2" stroke="#75613e" fill="none" opacity=".55"/>
        <path d="M41 59 V41 H59 M1221 41 H1239 V59 M41 661 V679 H59 M1221 679 H1239 V661" fill="none" stroke="#75613e" strokeWidth="2"/>
        <g transform="translate(1178 165)" fill="#78613e" stroke="#78613e"><path d="M0 -38 L8 0 L0 -7 L-8 0Z" fill="#78613e"/><path d="M0 30 L8 0 L0 7 L-8 0Z" fill="none"/><circle r="22" fill="none" opacity=".5"/><text y="-49" textAnchor="middle" fontSize="13" stroke="none">北</text></g>
        <g opacity=".75"><rect x="1013" y="238" width="185" height="145" fill="#dac89d" stroke="#927b52" strokeWidth=".8"/><g clipPath="url(#inset-clip)"><rect x="1013" y="238" width="185" height="145" fill="#a6b2a3"/><path d={insetLandPath} fill="#ddcca5" stroke="#8f805e" strokeWidth=".6"/><path d={insetRoute} stroke={accent} strokeWidth="3" fill="none"/></g><text x="1105" y="402" fontSize="11" textAnchor="middle" letterSpacing="2" fill="#796441">东亚地理定位</text></g>
      </svg>
      <div style={{position:'absolute',left:40,right:330,top:35,height:175,background:'linear-gradient(180deg, rgba(233,217,179,.9) 0%, rgba(233,217,179,.65) 65%, rgba(233,217,179,0) 100%)',pointerEvents:'none'}}/>
      <div style={{position:'absolute',left:40,right:40,bottom:85,height:120,background:'linear-gradient(180deg, rgba(224,204,163,0) 0%, rgba(224,204,163,.76) 40%, rgba(224,204,163,.9) 100%)',pointerEvents:'none'}}/>
      <div style={{position:'absolute',left:62,top:52,fontFamily:'sans-serif',fontSize:12,letterSpacing:5,color:'#735f3c'}}>CHRONOATLAS / 地理与历史的影像志</div>
      <div style={{position:'absolute',left:62,top:85,display:'flex',gap:18,alignItems:'center'}}><div style={{width:5,height:50,background:accent}}/><h1 style={{fontSize:42,margin:0,fontWeight:500,letterSpacing:3}}>{title}</h1></div>
      <div style={{position:'absolute',left:64,top:155,fontSize:14,letterSpacing:6,color:'#806d49'}}>河西走廊 · 从地理看历史</div>
      <div style={{position:'absolute',left:65,top:223,fontSize:12,letterSpacing:3,color:'#826b46',writingMode:'vertical-rl'}}>东联中原　西通西域</div>
      <div style={{position:'absolute',left:70,bottom:115,right:70,opacity:captionOpacity,display:'flex',gap:25,alignItems:'center'}}><span style={{color:accent,fontFamily:'Georgia',fontSize:42}}>{String(chapter+1).padStart(2,'0')}</span><div><div style={{fontSize:12,color:'#8a714d',letterSpacing:4,marginBottom:9}}>{['通向西方','地理通道','城市节点','历史分量'][chapter]}</div><div style={{fontSize:24,letterSpacing:1}}>{scenes[chapter]??''}</div></div></div>
      <div style={{position:'absolute',left:65,right:65,bottom:79,height:2,background:'#937b50'}}><div style={{width:`${seconds/30*100}%`,height:3,background:accent}}/>{[0,6,14,23].map((t,i)=><span key={t} style={{position:'absolute',left:`${t/30*100}%`,top:11,fontSize:11,color:chapter===i?accent:'#7b6948',letterSpacing:1}}>{['01 开篇','02 通道','03 城市','04 结语'][i]}</span>)}</div>
      <div style={{position:'absolute',left:65,bottom:29,fontSize:10,color:'#7e6a49',letterSpacing:1}}>地理底图 Natural Earth · 现代城市参考点 · 连线为通道示意，非历史行军路线或疆界</div>
      <div style={{position:'absolute',right:64,bottom:28,fontFamily:'monospace',fontSize:11,color:'#7e6a49'}}>{seconds.toFixed(1).padStart(4,'0')} / 30.0s</div>
    </AbsoluteFill>
  </AbsoluteFill>;
};
