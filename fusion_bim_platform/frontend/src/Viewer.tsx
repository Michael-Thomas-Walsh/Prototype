import {ModelMeshes} from './MeshViewer';
import type {MeshManifest} from './MeshViewer';
import {Canvas,ThreeEvent} from '@react-three/fiber';
import {OrbitControls,Grid,PerspectiveCamera} from '@react-three/drei';
import {useEffect,useMemo,useRef,useState} from 'react';
import {useThree} from '@react-three/fiber';
import * as THREE from 'three';
import type {Element,Discipline} from './types';
import {COLORS,DISCIPLINES} from './types';
const SKIP=new Set(['Spaces','Rooms','Analytical Surfaces','Electrical Circuits','Sheets','Grids','Levels']);
function center(e:Element):[number,number,number]{const b=e.bounds;return [(b[0]+b[3])/2,(b[2]+b[5])/2,-(b[1]+b[4])/2];}
function geometry(e:Element){const b=e.bounds;return [Math.max(.02,b[3]-b[0]),Math.max(.02,b[5]-b[2]),Math.max(.02,b[4]-b[1])] as const;}
function Instances({items,color,onPick,selectedIds,ghost}:{items:Element[];color:string;onPick:(e:Element)=>void;selectedIds:Set<string>;ghost:boolean}){
 const ref=useRef<THREE.InstancedMesh>(null);
 const geometryObj=useMemo(()=>new THREE.BoxGeometry(1,1,1),[]);
 const material=useMemo(()=>new THREE.MeshStandardMaterial({color,transparent:true,opacity:ghost?.09:.48,roughness:.86,metalness:.04,depthWrite:!ghost}),[color,ghost]);
 useEffect(()=>{const mesh=ref.current;if(!mesh)return;const m=new THREE.Matrix4();const p=new THREE.Vector3(),q=new THREE.Quaternion(),s=new THREE.Vector3();items.forEach((e,i)=>{const c=center(e),g=geometry(e);p.set(...c);s.set(...g);m.compose(p,q,s);mesh.setMatrixAt(i,m);mesh.setColorAt(i,new THREE.Color(selectedIds.has(e.id)?'#ff644f':color));});mesh.instanceMatrix.needsUpdate=true;if(mesh.instanceColor)mesh.instanceColor.needsUpdate=true;mesh.computeBoundingSphere();},[items,color,selectedIds]);
 return <instancedMesh ref={ref} args={[geometryObj,material,items.length]} onClick={(event:ThreeEvent<MouseEvent>)=>{event.stopPropagation();if(event.instanceId!==undefined)onPick(items[event.instanceId]);}} />;
}
function Highlight({elements,ghost}:{elements:Element[];ghost:boolean}){return <>{elements.map(e=>{const c=center(e),g=geometry(e);return <group key={e.id} position={c} scale={g}><mesh raycast={()=>null}><boxGeometry args={[1,1,1]}/><meshBasicMaterial color="#ee9d63" transparent opacity={ghost?.045:0} depthWrite={false}/></mesh><lineSegments raycast={()=>null}><edgesGeometry args={[new THREE.BoxGeometry(1,1,1)]}/><lineBasicMaterial color="#f2ae79" transparent opacity={ghost?.24:.0} depthTest={true}/></lineSegments></group>;})}</>}
function CameraTarget({target,focus}:{target:Element|null;focus:Element[]}){const controls=useRef<any>(null);const {camera}=useThree();useEffect(()=>{if(!controls.current)return;
 if(focus.length){const box=new THREE.Box3();focus.forEach(e=>{const b=e.bounds;box.union(new THREE.Box3(new THREE.Vector3(b[0],b[2],-b[4]),new THREE.Vector3(b[3],b[5],-b[1])))});const centre=box.getCenter(new THREE.Vector3());const size=box.getSize(new THREE.Vector3());const radius=Math.max(2,size.length());camera.position.copy(centre.clone().add(new THREE.Vector3(radius*.9,radius*.7,radius*.9)));controls.current.target.copy(centre);camera.updateProjectionMatrix();controls.current.update();return}
 if(!target)return;const p=center(target);controls.current.target.set(...p);controls.current.update();},[target,focus.map(e=>e.id).join('|'),camera]);return <OrbitControls ref={controls} makeDefault minDistance={1} maxDistance={650} enableDamping dampingFactor={.08}/>;}
export default function Viewer({elements,visible,onSelect,selection,activeIds,ghost,shownIds,meshManifest,meshMode,onClear,isolate=false}:{elements:Element[];visible:Set<Discipline>;onSelect:(e:Element)=>void;selection:Element|null;activeIds:Set<string>;ghost:boolean;shownIds:Set<string>|null;meshManifest:MeshManifest|null;meshMode:boolean;onClear:()=>void;isolate?:boolean}){
 const [meshReport,setMeshReport]=useState<{loaded:number;total:number;error?:string;matched?:number;expected?:number}|null>(null);
 const groups=useMemo(()=>DISCIPLINES.map(d=>({discipline:d,items:elements.filter(e=>e.discipline===d&&!SKIP.has(e.category) && (!shownIds||shownIds.has(e.id)))})),[elements,shownIds]);
 const selectedIds=useMemo(()=>new Set([...activeIds,...(selection?[selection.id]:[])]),[activeIds,selection]);
 const index=useMemo(()=>new Map(elements.map(e=>[e.id,e])),[elements]);
 const highlights=useMemo(()=>[...selectedIds].map(id=>index.get(id)).filter((e):e is Element=>!!e),[selectedIds,index]);
 const target=selection||highlights[0]||null;
 return <div className="viewer"><Canvas gl={{antialias:true}} camera={{position:[105,87,120],fov:46,near:.1,far:2000}} onPointerMissed={()=>onClear()}><color attach="background" args={['#111d2a']}/><ambientLight intensity={.72}/><hemisphereLight args={["#d9ecff","#586673",2.1]}/><directionalLight position={[70,120,50]} intensity={2.9}/><directionalLight position={[-70,65,-60]} intensity={1.5}/><PerspectiveCamera makeDefault position={[105,87,120]} fov={46}/><Grid position={[0,-1,0]} args={[600,600]} cellSize={10} sectionSize={50} cellColor="#304455" sectionColor="#486079" fadeDistance={340} fadeStrength={2} infiniteGrid/><axesHelper args={[14]}/>{!meshMode&&groups.filter(g=>visible.has(g.discipline)&&g.items.length).map(g=><Instances key={g.discipline} items={isolate&&selectedIds.size?g.items.filter(e=>selectedIds.has(e.id)):g.items} color={COLORS[g.discipline]} onPick={onSelect} selectedIds={selectedIds} ghost={ghost&&highlights.length>0}/>)}{meshMode&&meshManifest&&<ModelMeshes manifest={meshManifest} visible={visible} active={selectedIds} ghost={ghost} isolate={isolate} onSelect={onSelect} elements={elements} onReport={setMeshReport}/>}{!meshMode&&<Highlight elements={highlights} ghost={true}/>}<CameraTarget target={target} focus={isolate?highlights:[]}/></Canvas>{meshMode&&<div style={{position:'absolute',left:14,top:14,zIndex:5,background:'#182635ee',color:'white',padding:'8px 12px',borderRadius:7,fontSize:12,maxWidth:'80%',pointerEvents:'none'}}>
  {!meshManifest?.chunks.length?'No mesh files in manifest — click Check latest Speckle version':meshReport?.error?`Mesh load error: ${meshReport.error}`:`Real geometry: ${meshReport?.loaded||0} / ${meshManifest.chunks.length} GLB chunks${isolate&&meshReport?.expected?` · Focus meshes: ${meshReport.matched??0}/${meshReport.expected}`:''}`}
 </div>}
 <div className="viewer-credit">{meshMode?"Actual transformed Speckle meshes · GLB · review coordinate alignment before reliance":"AABB geometry proxies · model coordinates in metres · NOT final BIM meshes"}</div></div>;
}
