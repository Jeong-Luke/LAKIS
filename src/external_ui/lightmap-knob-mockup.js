// Source-faithful UI-only port of ComfyUI-LAKIS-Light-Control/web/lakis_light_control.js.
// It intentionally owns no workflow bridge state.
const canvas = document.querySelector("#lightOrbitCanvas");
const readout = document.querySelector("#lightOrbitStatus");
const controlsRoot = document.querySelector("#lightMockControls");
const toggle = document.querySelector("#lightMockToggle");
const reset = document.querySelector("#lightMockReset");
const unavailableNotice = document.querySelector("#lightUnavailableNotice");
const WIDTH = 560;
const HEIGHT = 360;
const WHEEL_STEP = .0003;
const clamp = (value, min, max) => Math.max(min, Math.min(max, Number(value)));
const LOCKED_VALUES = { pos_x:.68, pos_y:.37, pos_z:-1, intensity:.91, ambient:.33, shadow:.65, exposure:0, rim:0, color_mode:"Neutral" };
const state = { ...LOCKED_VALUES };
let viewYaw = 0;
let viewPitch = .42;
let dragging = null;
let noticeTimer = 0;

const fields = [
  ["pos_x","lightXSlider","lightX"], ["pos_y","lightYSlider","lightY"], ["pos_z","lightZSlider","lightZ"],
  ["intensity","lightIntensitySlider","lightIntensity"], ["ambient","lightAmbientSlider","lightAmbient"],
  ["shadow","lightShadowSlider","lightShadow"], ["exposure","lightExposureSlider","lightExposure"],
  ["rim","lightRimSlider","lightRim"]
];

const dpr = Math.min(window.devicePixelRatio || 1, 2);
canvas.width = WIDTH * dpr;
canvas.height = HEIGHT * dpr;
const ctx = canvas.getContext("2d");
ctx.scale(dpr, dpr);

function project(x, y, z) {
  const cosine = Math.cos(viewYaw);
  const sine = Math.sin(viewYaw);
  const horizontal = x * cosine + z * sine;
  const depth = -x * sine + z * cosine;
  const scale = 78;
  return {
    x: WIDTH / 2 + horizontal * scale,
    y: HEIGHT / 2 - (y - .7) * scale * Math.cos(viewPitch) + depth * scale * Math.sin(viewPitch),
    depth
  };
}

function ellipse(radius, elevation, stroke, dashed = true) {
  ctx.beginPath();
  for (let index = 0; index <= 80; index += 1) {
    const angle = index / 80 * Math.PI * 2;
    const point = project(radius * Math.sin(angle), elevation, radius * Math.cos(angle));
    index ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y);
  }
  ctx.strokeStyle = stroke;
  ctx.lineWidth = 1.8;
  ctx.setLineDash(dashed ? [5,7] : []);
  ctx.stroke();
  ctx.setLineDash([]);
}

function verticalOrbit(radius, azimuth, stroke) {
  ctx.beginPath();
  for (let index = 0; index <= 80; index += 1) {
    const angle = index / 80 * Math.PI * 2;
    const horizontal = radius * Math.cos(angle);
    const point = project(horizontal * Math.sin(azimuth), .7 + radius * Math.sin(angle), horizontal * Math.cos(azimuth));
    index ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y);
  }
  ctx.strokeStyle = stroke;
  ctx.lineWidth = 1.8;
  ctx.setLineDash([5,7]);
  ctx.stroke();
  ctx.setLineDash([]);
}

function elevationOrbit(radius, elevation, stroke) {
  const horizontal = radius * Math.cos(elevation);
  const height = .7 + radius * Math.sin(elevation);
  ctx.beginPath();
  for (let index = 0; index <= 80; index += 1) {
    const angle = index / 80 * Math.PI * 2;
    const point = project(horizontal * Math.sin(angle), height, horizontal * Math.cos(angle));
    index ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y);
  }
  ctx.strokeStyle = stroke;
  ctx.lineWidth = 1.4;
  ctx.setLineDash([3,7]);
  ctx.stroke();
  ctx.setLineDash([]);
}

function point3d(x, y, z, label) {
  const point = project(x,y,z);
  ctx.fillStyle = "#75d9e9";
  ctx.beginPath();
  ctx.arc(point.x,point.y,5,0,Math.PI*2);
  ctx.fill();
  ctx.fillStyle = "#eef8ff";
  ctx.font = "700 13px Consolas";
  ctx.textAlign = "center";
  ctx.fillText(label,point.x,point.y-10);
}

function drawLightIcon(point, intensity) {
  const radius = 10 + Math.min(1,intensity) * 4;
  ctx.save();
  ctx.translate(point.x,point.y);
  ctx.strokeStyle = "rgba(255,215,105,.82)";
  ctx.lineWidth = 1.7;
  for (let index = 0; index < 8; index += 1) {
    const angle = index * Math.PI / 4;
    ctx.beginPath();
    ctx.moveTo(Math.cos(angle)*(radius+4),Math.sin(angle)*(radius+4));
    ctx.lineTo(Math.cos(angle)*(radius+11),Math.sin(angle)*(radius+11));
    ctx.stroke();
  }
  ctx.fillStyle="#ffb84f";
  ctx.strokeStyle="#ffe19a";
  ctx.lineWidth=2;
  ctx.beginPath();
  ctx.moveTo(0,-radius);ctx.lineTo(radius*.82,0);ctx.lineTo(0,radius);ctx.lineTo(-radius*.82,0);ctx.closePath();ctx.fill();ctx.stroke();
  ctx.fillStyle="#fff0ad";ctx.beginPath();ctx.arc(0,0,4.2,0,Math.PI*2);ctx.fill();ctx.restore();
}

function syncControls() {
  for (const [key,sliderId,numberId] of fields) {
    document.querySelector(`#${sliderId}`).value = state[key];
    document.querySelector(`#${numberId}`).value = Number(state[key]).toFixed(2);
  }
  document.querySelector("#lightColor").value = state.color_mode;
}

function draw() {
  ctx.clearRect(0,0,WIDTH,HEIGHT);
  const background=ctx.createLinearGradient(0,0,0,HEIGHT);background.addColorStop(0,"#151a20");background.addColorStop(1,"#222932");ctx.fillStyle=background;ctx.fillRect(0,0,WIDTH,HEIGHT);
  const posX=clamp(state.pos_x,-1,1),posY=clamp(state.pos_y,-1,1),posZ=clamp(state.pos_z,-1,1),intensity=clamp(state.intensity,0,2);
  const radius=1.7-.7*posZ,angle=posX*Math.PI,elevation=posY*Math.PI/2;
  ellipse(radius,.7,"rgba(74,201,217,.34)");
  verticalOrbit(radius,angle,"rgba(255,137,75,.38)");
  elevationOrbit(radius,elevation,"rgba(111,215,235,.25)");
  const horizontal=radius*Math.cos(elevation);
  const light={x:horizontal*Math.sin(angle),y:.7+radius*Math.sin(elevation),z:horizontal*Math.cos(angle)};
  point3d(0,.7,radius,"F");point3d(0,.7,-radius,"B");point3d(radius,.7,0,"L");point3d(-radius,.7,0,"R");
  const center=project(0,.7,0),lightPoint=project(light.x,light.y,light.z);
  ctx.strokeStyle="rgba(255,210,103,.72)";ctx.setLineDash([5,6]);ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(center.x,center.y);ctx.lineTo(lightPoint.x,lightPoint.y);ctx.stroke();ctx.setLineDash([]);
  ctx.save();
  ctx.translate(center.x,center.y);
  ctx.scale(1.7,1.7);
  ctx.shadowColor="rgba(83,211,226,.72)";
  ctx.shadowBlur=12;
  const personGradient=ctx.createLinearGradient(-8,-16,9,17);
  personGradient.addColorStop(0,"#e8ffff");personGradient.addColorStop(.45,"#73d9e5");personGradient.addColorStop(1,"#2d7885");
  ctx.fillStyle=personGradient;ctx.strokeStyle="rgba(221,255,255,.72)";ctx.lineWidth=1;
  ctx.beginPath();ctx.arc(0,-11,5,0,Math.PI*2);ctx.fill();ctx.stroke();
  ctx.beginPath();ctx.moveTo(-7,-4);ctx.quadraticCurveTo(0,-8,7,-4);ctx.lineTo(5,7);ctx.lineTo(3,7);ctx.lineTo(3,16);ctx.lineTo(0,16);ctx.lineTo(0,8);ctx.lineTo(-3,16);ctx.lineTo(-6,16);ctx.lineTo(-4,7);ctx.lineTo(-6,7);ctx.closePath();ctx.fill();ctx.stroke();ctx.restore();
  drawLightIcon(lightPoint,intensity);
  const degrees=Math.round(posX*180);let side;if(Math.abs(posX)>.85)side="후면";else if(posX>.05)side=`좌측 ${Math.abs(degrees)}°`;else if(posX<-.05)side=`우측 ${Math.abs(degrees)}°`;else side="정면 0°";
  const elevationDegrees=Math.round(posY*90);const distance=posZ>.2?"가까움":posZ<-.2?"멀음":"중간";readout.textContent=`${side} · 상하 ${elevationDegrees}° · 거리 ${distance}`;
}

function refresh(){syncControls();draw();}
for(const [key,sliderId,numberId] of fields){const apply=event=>{state[key]=Number(event.target.value);refresh();};document.querySelector(`#${sliderId}`).addEventListener("input",apply);document.querySelector(`#${numberId}`).addEventListener("change",apply);}
document.querySelector("#lightColor").addEventListener("change",event=>{state.color_mode=event.target.value;});

function canvasPoint(event){const rect=canvas.getBoundingClientRect();return{x:(event.clientX-rect.left)*WIDTH/rect.width,y:(event.clientY-rect.top)*HEIGHT/rect.height};}
canvas.addEventListener("pointerdown",event=>{event.stopPropagation();canvas.setPointerCapture(event.pointerId);const point=canvasPoint(event);const mode=event.button===2||event.altKey?"view":"light";dragging={mode,pointerId:event.pointerId,x:point.x,y:point.y,posX:state.pos_x,posY:state.pos_y,viewYaw,viewPitch};canvas.style.cursor=mode==="view"?"move":"grabbing";event.preventDefault();});
canvas.addEventListener("pointermove",event=>{if(!dragging||dragging.pointerId!==event.pointerId)return;const point=canvasPoint(event);if(dragging.mode==="view"){viewYaw=dragging.viewYaw-(point.x-dragging.x)/WIDTH*Math.PI*2;viewPitch=clamp(dragging.viewPitch+(point.y-dragging.y)/HEIGHT*1.5,.12,1.15);draw();}else{let value=dragging.posX+(point.x-dragging.x)/(WIDTH/2);while(value>1)value-=2;while(value<-1)value+=2;state.pos_x=value;state.pos_y=clamp(dragging.posY-(point.y-dragging.y)/(HEIGHT/2),-1,1);refresh();}event.preventDefault();});
function stopDrag(event){if(!dragging||dragging.pointerId!==event.pointerId)return;dragging=null;canvas.style.cursor="crosshair";try{canvas.releasePointerCapture?.(event.pointerId);}catch{}}
canvas.addEventListener("pointerup",stopDrag);canvas.addEventListener("pointercancel",stopDrag);canvas.addEventListener("contextmenu",event=>event.preventDefault());
canvas.addEventListener("wheel",event=>{event.preventDefault();state.pos_z=clamp(state.pos_z-event.deltaY*WHEEL_STEP,-1,1);refresh();},{passive:false});
canvas.addEventListener("dblclick",event=>{if(event.shiftKey){viewYaw=0;viewPitch=.42;draw();}else{state.pos_x=0;state.pos_y=0;refresh();}});
toggle.addEventListener("click",()=>{
  toggle.classList.remove("on");
  toggle.setAttribute("aria-pressed","false");
  controlsRoot.classList.add("is-disabled");
  unavailableNotice.hidden=false;
  clearTimeout(noticeTimer);
  noticeTimer=setTimeout(()=>{unavailableNotice.hidden=true;},1800);
});
reset.addEventListener("click",()=>{Object.assign(state,LOCKED_VALUES);viewYaw=0;viewPitch=.42;refresh();});
refresh();
