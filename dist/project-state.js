// Local project state shared across the demo stages.
window.createMakoraProject = function(researchBlocks, conceptBlocks) {
// Project inputs and edited concept documents are kept locally on this device.
const projectKey='makora.project.context.v1';
let projectData; try { projectData=JSON.parse(localStorage.getItem(projectKey))||{}; } catch { projectData={}; }
projectData.documents=projectData.documents||{};
for(const doc of [...researchBlocks,...conceptBlocks]) if(typeof projectData.documents[doc.title]==='string') doc.md=projectData.documents[doc.title];
function saveProject(){try{localStorage.setItem(projectKey,JSON.stringify(projectData));return true}catch{return false}}
function projectSignature(){const value=JSON.stringify({source:projectData.source||null,research:researchBlocks,concept:conceptBlocks});let h=2166136261;for(const c of value)h=Math.imul(h^c.charCodeAt(0),16777619);return (h>>>0).toString(16)}
const project={
  source:()=>projectData.source||null,
  signature:projectSignature,
  isApproved:()=>!!projectData.approved&&projectData.approved.signature===projectSignature(),
  approve:()=>{const previous=projectData.approved;projectData.approved={signature:projectSignature(),time:new Date().toISOString()};if(saveProject())return true;projectData.approved=previous;return false},
  saveDocument:(doc,value)=>{const old=doc.md,stored=projectData.documents[doc.title];doc.md=value;projectData.documents[doc.title]=value;if(saveProject())return true;doc.md=old;if(stored===undefined)delete projectData.documents[doc.title];else projectData.documents[doc.title]=stored;return false},
  setSource:(source)=>{const old=projectData.source;projectData.source=source;if(saveProject())return true;projectData.source=old;return false},
  context:()=>({source:projectData.source||null,research:researchBlocks.map(x=>({...x})),concept:conceptBlocks.map(x=>({...x})),approved:project.isApproved(),signature:projectSignature()})
};

return project;
};
