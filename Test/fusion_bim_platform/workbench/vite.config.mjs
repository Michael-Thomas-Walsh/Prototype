import {defineConfig} from 'vite';
export default defineConfig({resolve:{dedupe:['react','react-dom']},server:{port:5173,strictPort:true,proxy:{'/api':'http://127.0.0.1:8000'}},build:{outDir:'dist'}});
