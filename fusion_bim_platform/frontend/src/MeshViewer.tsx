import {useEffect,useMemo,useState,useRef} from 'react';
import {useThree} from '@react-three/fiber';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import * as THREE from 'three';
import type {Element,Discipline} from './types';
import {COLORS} from './types';
export type MeshChunk={url:string;discipline:Discipline;elementCount:number};
export type MeshManifest={status:string;chunks:MeshChunk[];exportedElements?:number;versionId?:string};
type Loaded={chunk:MeshChunk;scene:THREE.Group};
export function ModelMeshes({manifest,visible,active,onSelect,elements,onReport,ghost=false,isolate=false}:{manifest:MeshManifest;visible:Set<Discipline>;active:Set<string>;onSelect:(e:Element)=>void;elements:Element[];ghost?:boolean;isolate?:boolean;onReport?:(p:{loaded:number;total:number;error?:string;matched?:number;expected?:number})=>void}){
 const lookup=useMemo(()=>new Map(elements.map(e=>[e.id,e])),[elements]);
 const [loaded,setLoaded]=useState<Record<string,Loaded>>({});
 const [problem,setProblem]=useState('');
 const {camera,controls,invalidate}=useThree();
 const fitted=useRef('');

 const key=manifest.chunks.map(c=>c.url).join('|');
 // GLB scene graph names are assigned to parent nodes by trimesh; mesh children
 // generally have generic names. Resolve an element ID through its ancestors.
 const resolveId=(node:THREE.Object3D):string|undefined=>{
   let cur:THREE.Object3D|null=node;
   while(cur){
     for(const candidate of [cur.userData.applicationId,cur.userData.name,cur.name]){
       if(candidate){const id=String(candidate).split('__part')[0];if(lookup.has(id))return id;}
     }
     cur=cur.parent;
   }
   return undefined;
 };
 // Sequential loading avoids memory spikes and makes cancellation deterministic.
 useEffect(()=>{
  let cancelled=false;
  const loader=new GLTFLoader();
  setLoaded({});setProblem('');fitted.current='';
  (async()=>{
   const result:Record<string,Loaded>={};
   for(const chunk of manifest.chunks){
    if(cancelled)break;
    try{
     const gltf=await loader.loadAsync(chunk.url);
     if(cancelled)break;
     result[chunk.url]={chunk,scene:gltf.scene};
     setLoaded({...result});
     onReport?.({loaded:Object.keys(result).length,total:manifest.chunks.length});
    }catch(ex){
     if(cancelled)break;
     const message=`Failed to load ${chunk.url}: ${String(ex)}`;
     console.error(message);
     setProblem(message);onReport?.({loaded:Object.keys(result).length,total:manifest.chunks.length,error:message});
    }
   }
  })();
  return()=>{cancelled=true};
 },[key]);
 // Materials, lighting response and restrained outlines make the model legible.
 useEffect(()=>{
  for(const {chunk,scene} of Object.values(loaded)){
   scene.traverse(node=>{
    if(!(node instanceof THREE.Mesh))return;
    const id=resolveId(node);
    const element=id?lookup.get(id):undefined;
    const selected=!!id&&active.has(id);
    node.visible=!isolate||active.size===0||selected;
    const c=element?.category.toLowerCase()||'';
    const base=c.includes('glass')||c.includes('glazing')?'#79abc0':
      c.includes('concrete')?'#a2aab0':c.includes('steel')?'#748899':
      c.includes('wall')?'#d4d7d6':c.includes('floor')?'#a9b4be':
      c.includes('duct')?'#74a99f':c.includes('pipe')?'#6b93ba':
      COLORS[chunk.discipline];
    if(!node.userData.fusionMaterial){
      // Cloned material prevents changes to one mesh changing others.
      node.material=new THREE.MeshStandardMaterial({color:base,roughness:.79,metalness:.04,side:THREE.DoubleSide,flatShading:true});
      node.userData.fusionMaterial=true;
      if(node.geometry && !node.geometry.hasAttribute('normal'))node.geometry.computeVertexNormals();
    }
    const mat=node.material as THREE.MeshStandardMaterial;
    mat.transparent=!isolate&&ghost&&active.size>0&&!selected;
    mat.opacity=mat.transparent?.19:1;mat.depthWrite=!mat.transparent;
    mat.color.set(selected?'#ff8861':base);
    mat.emissive.set(selected?'#6e2614':'#000000');
    mat.emissiveIntensity=selected?.34:0;
    // Edges only on selected elements to avoid millions of lines and poor frame rates.
    const existing=node.getObjectByName('fusion-selection-edges');
    if(selected && !existing){
      const edges=new THREE.LineSegments(new THREE.EdgesGeometry(node.geometry,28),new THREE.LineBasicMaterial({color:'#ffe0ad',transparent:true,opacity:.94,depthTest:true}));
      edges.name='fusion-selection-edges';edges.raycast=()=>{};node.add(edges);
    }else if(!selected&&existing){
      node.remove(existing);
      (existing as THREE.LineSegments).geometry.dispose();
      ((existing as THREE.LineSegments).material as THREE.Material).dispose();
    }
   });
  }
  const found=new Set<string>();
  for(const {scene} of Object.values(loaded)){scene.traverse(node=>{if(node instanceof THREE.Mesh){const id=resolveId(node);if(id&&active.has(id))found.add(id)}})}
  if(isolate&&active.size&&Object.keys(loaded).length===manifest.chunks.length){
    onReport?.({loaded:Object.keys(loaded).length,total:manifest.chunks.length,matched:found.size,expected:active.size,
      error:found.size<active.size?`Missing selected GLB geometry: ${[...active].filter(id=>!found.has(id)).join(', ')}`:undefined});
  }
  invalidate();
 },[loaded,active,lookup,ghost,isolate,invalidate]);
 // Fit camera once model geometry is available; previous fixed camera missed distant Revit origins.
 useEffect(()=>{
  if(!Object.keys(loaded).length||fitted.current===key)return;
  const bounds=new THREE.Box3();
  Object.values(loaded).forEach(({scene})=>{scene.updateWorldMatrix(true,true);bounds.expandByObject(scene)});
  if(bounds.isEmpty())return;
  const size=bounds.getSize(new THREE.Vector3());const centre=bounds.getCenter(new THREE.Vector3());
  const max=Math.max(1,size.x,size.y,size.z);
  camera.position.copy(centre.clone().add(new THREE.Vector3(max*1.3,max*.9,max*1.3)));
  camera.near=Math.max(.01,max/10000);camera.far=Math.max(2000,max*15);camera.updateProjectionMatrix();
  if(controls && 'target' in controls){(controls as any).target.copy(centre);(controls as any).update()}
  camera.lookAt(centre);invalidate();fitted.current=key;
 },[loaded,camera,controls,key,invalidate]);
 return <>
  <group onClick={ev=>{let obj:THREE.Object3D|null=ev.object;while(obj){const id=resolveId(obj);const element=id?lookup.get(id):undefined;if(element){ev.stopPropagation();onSelect(element);return;}obj=obj.parent;}}}>
   {Object.values(loaded).filter(({chunk})=>visible.has(chunk.discipline)).map(({chunk,scene})=><primitive key={chunk.url} object={scene}/>)}
  </group>
  {problem&&<HtmlError message={problem}/>}
 </>;
}
function HtmlError({message}:{message:string}){useEffect(()=>{window.dispatchEvent(new CustomEvent('fusion-mesh-error',{detail:message}))},[message]);return null}
