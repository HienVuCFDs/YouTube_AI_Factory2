import React from 'react';
import {AbsoluteFill, Composition, registerRoot, useCurrentFrame, useVideoConfig, spring} from 'remotion';

type IconName = 'person'|'robot'|'message'|'brain'|'check'|'question'|'spark'|'heart'|'chart'|'clock';
type Layer = {
  id: string; preset: string; text: string; secondary: string;
  start_seconds: number; end_seconds: number; animation: string; palette: string;
  bounds: {x: number; y: number; width: number; height: number};
  items: {label: string; icon: IconName; at_seconds: number}[];
};
type Props = {width: number; height: number; fps: number; duration_seconds: number; graphic_layers: Layer[]};

const colors: Record<string, {accent: string; pale: string; ink: string}> = {
  blue: {accent: '#2463eb', pale: '#eaf0ff', ink: '#102047'},
  pink: {accent: '#e34782', pale: '#fff0f6', ink: '#402037'},
  lime: {accent: '#b7ef36', pale: '#effbd6', ink: '#18352a'},
  amber: {accent: '#e79b19', pale: '#fff5da', ink: '#453317'},
};

// Vector primitives are authored here: no downloaded icon font or remote assets.
const Icon: React.FC<{name: IconName; color: string}> = ({name, color}) => {
  const drawings: Record<IconName, React.ReactNode> = {
    person: <><circle cx="32" cy="17" r="10"/><path d="M13 56v-9a19 19 0 0 1 38 0v9"/></>,
    robot: <><rect x="10" y="19" width="44" height="35" rx="12"/><path d="M32 19V9M5 30v13M59 30v13M24 44h16"/><circle cx="23" cy="32" r="2"/><circle cx="41" cy="32" r="2"/><circle cx="32" cy="7" r="3"/></>,
    message: <><path d="M12 10h40a5 5 0 0 1 5 5v29a5 5 0 0 1-5 5H29L15 59V49h-3a5 5 0 0 1-5-5V15a5 5 0 0 1 5-5Z"/><path d="M18 25h28M18 35h20"/></>,
    brain: <><path d="M32 12C23 2 14 8 14 17 3 18 3 31 9 35 2 49 16 57 24 52c2 8 8 4 8-1V12Zm0 0C41 2 50 8 50 17c11 1 11 14 5 18 7 14-7 22-15 17-2 8-8 4-8-1V12Z"/><path d="M14 17q13 0 10 12M9 35q14-8 15 5M50 17q-13 0-10 12M55 35q-14-8-15 5"/></>,
    check: <><circle cx="32" cy="32" r="26"/><path d="m18 32 10 10 19-22"/></>,
    question: <><circle cx="32" cy="32" r="26"/><path d="M23 23c0-13 22-13 19 0-1 6-10 6-10 14"/><circle cx="32" cy="46" r="1.7"/></>,
    spark: <path d="m32 4 7 20 21 8-21 7-7 21-8-21-20-7 20-8Z"/>,
    heart: <path d="M32 55 10 33C-6 13 18-1 32 17 46-1 70 13 54 33Z"/>,
    chart: <><path d="M8 7v49h49"/><path d="M18 46V32h7v14M31 46V22h7v24M44 46V12h7v34"/></>,
    clock: <><circle cx="32" cy="32" r="26"/><path d="M32 15v18l12 7"/></>,
  };
  return <svg viewBox="0 0 64 64" width="100%" height="100%" fill="none" stroke={color} strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round">{drawings[name]}</svg>;
};

const clamp = (n: number) => Math.max(0, Math.min(1, n));
const Graphic: React.FC<{layer: Layer}> = ({layer}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const start = Math.round(layer.start_seconds * fps), end = Math.round(layer.end_seconds * fps);
  if (frame < start || frame >= end) return null;
  const local = frame - start;
  const entrance = spring({frame: local, fps, config: {damping: 18, stiffness: 190, mass: .65}});
  const leave = clamp((end - frame) / Math.max(1, fps * .18));
  const opacity = clamp(local / Math.max(1, fps * .12)) * leave;
  const c = colors[layer.palette] || colors.blue;
  const w = layer.bounds.width * width, h = layer.bounds.height * height;
  const scale = layer.animation === 'pop' ? .82 + .18 * entrance : 1;
  const translate = layer.animation === 'slide_up' ? (1 - entrance) * h * .18 : 0;
  const fontSize = Math.min(w * .088, h * .29, width * .087);
  const common: React.CSSProperties = {position: 'absolute', left: layer.bounds.x * width,
    top: layer.bounds.y * height, width: w, height: h, opacity,
    transform: `translateY(${translate}px) scale(${scale})`, transformOrigin: '50% 50%',
    fontFamily: 'Arial, sans-serif', color: c.ink, boxSizing: 'border-box'};
  const title: React.CSSProperties = {fontSize, fontWeight: 900, lineHeight: 1.13, textAlign: 'center',
    whiteSpace: 'pre-wrap', overflowWrap: 'anywhere'};
  const secondary = layer.secondary && <div style={{fontSize: fontSize * .43, fontWeight: 600,
    lineHeight: 1.3, textAlign: 'center', marginTop: h * .04}}>{layer.secondary}</div>;

  if (layer.preset === 'brush_label') return <div style={common}>
    <svg viewBox="0 0 1000 240" preserveAspectRatio="none" width="100%" height="100%" style={{position:'absolute'}}>
      <path d="M25 27 188 12 342 26 486 9 657 21 822 10 973 25 953 61 991 78 968 110 985 142 958 171 977 215 797 223 650 209 482 232 331 218 181 228 16 213 34 177 8 150 30 119 14 86 41 55Z" fill={c.accent}/>
    </svg>
    <div style={{position:'absolute', inset:'12% 5%', display:'flex', flexDirection:'column', justifyContent:'center', color:layer.palette === 'lime' ? c.ink : 'white'}}>
      <div style={{...title, fontStyle:'italic', fontSize:Math.min(w * .087, h * .37)}}>{layer.text}</div>{secondary}
    </div>
  </div>;

  if (layer.preset === 'icon_flow') return <div style={{...common, background:'rgba(255,255,255,0.97)',
    borderRadius:w*.035, border:`${Math.max(1,w*.003)}px solid ${c.pale}`, boxShadow:`0 ${h*.04}px ${h*.12}px #14203512`, padding:`${h*.08}px ${w*.035}px`}}>
    <div style={{...title, fontSize:Math.min(w*.047,h*.14), marginBottom:h*.07}}>{layer.text}</div>
    <div style={{display:'flex', alignItems:'center', justifyContent:'center', height:'68%'}}>
      {layer.items.map((item, i) => {
        const progress = spring({frame:local - Math.round(item.at_seconds*fps), fps,
          config:{damping:20, stiffness:180}});
        const visible = local >= item.at_seconds*fps;
        return <React.Fragment key={i}>
          {i > 0 && <div style={{width:'8%', color:c.accent, fontSize:w*.045, opacity:visible?progress:0}}>→</div>}
          <div style={{width:`${78/layer.items.length}%`, textAlign:'center', alignSelf:'stretch',
            opacity:visible?clamp(progress):0, transform:`translateY(${(1-progress)*15}px)`}}>
            <div style={{height:'58%', margin:'0 auto 5%', aspectRatio:'1', background:c.pale,
              borderRadius:'24%', padding:h*.028, boxSizing:'border-box'}}><Icon name={item.icon} color={c.accent}/></div>
            <div style={{fontSize:Math.min(w*.038,h*.1), fontWeight:700,lineHeight:1.2}}>{item.label}</div>
          </div>
        </React.Fragment>;
      })}
    </div>
  </div>;

  if (layer.preset === 'speech_bubble') return <div style={common}>
    <div style={{height:'86%', background:c.pale, borderRadius:w*.04, border:`${w*.004}px solid ${c.accent}`,
      padding:'5%', boxSizing:'border-box', display:'flex', alignItems:'center', justifyContent:'center', flexDirection:'column'}}>
      <div style={{...title, fontSize:fontSize*.8}}>{layer.text}</div>{secondary}
    </div>
    <svg viewBox="0 0 50 24" style={{position:'absolute',left:'15%',bottom:1,width:'12%',height:'17%'}}>
      <path d="M2 0 37 0 36 21Z" fill={c.pale} stroke={c.accent} strokeWidth="2"/>
      <path d="M4 0h32" stroke={c.pale} strokeWidth="5"/>
    </svg>
  </div>;

  if (layer.preset === 'stat_card') return <div style={{...common, background:c.ink, color:'white',
    borderRadius:w*.04, padding:'3%', display:'flex', flexDirection:'column', justifyContent:'center',
    boxShadow:`${w*.01}px ${w*.01}px 0 ${c.accent}`}}>
    <div style={{...title, color:c.accent, fontSize:Math.min(w*.18,h*.5)}}>{layer.text}</div>{secondary}
  </div>;

  return <div style={{...common, display:'flex', flexDirection:'column', justifyContent:'center'}}>
    <div style={{...title, color:c.ink, fontSize:Math.min(w*.10,h*.38),
      paintOrder:'stroke fill', WebkitTextStroke:`${width*.009}px white`,
      textShadow:`0 ${width*.004}px ${width*.018}px ${c.accent}70`}}>{layer.text}</div>
    <div style={{height:Math.max(3,height*.004),width:`${entrance*65}%`,background:c.accent,
      margin:`${h*.06}px auto 0`,borderRadius:8}}/>{secondary}
  </div>;
};

const SceneGraphics: React.FC<Props> = props => <AbsoluteFill style={{backgroundColor:'transparent'}}>
  {props.graphic_layers.map(layer => <Graphic key={layer.id} layer={layer}/>)}
</AbsoluteFill>;

const defaults: Props = {width:720,height:1280,fps:30,duration_seconds:5,graphic_layers:[]};
const Root = () => <Composition id="SceneGraphics" component={SceneGraphics} defaultProps={defaults}
  width={720} height={1280} fps={30} durationInFrames={150}
  calculateMetadata={({props}) => ({width:props.width,height:props.height,fps:props.fps,
    durationInFrames:Math.max(1,Math.ceil(props.duration_seconds*props.fps))})}/>;
registerRoot(Root);
