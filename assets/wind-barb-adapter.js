/* Adapter for wind-barbs 1.0.11. Original generator remains unchanged in vendor/. */
(function(){
const compass=['N','NE','E','SE','S','SW','W','NW'];
const escape=value=>String(value).replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;').replaceAll('>','&gt;');
function svg(speed,bearing){
 if(!Number.isFinite(speed)||speed<0) return null;
 const knots=speed/0.5144444444444445;
 const rounded=5*Math.round(knots/5);
 if(rounded>0&&!Number.isFinite(bearing)) return null;
 const angle=rounded===0?0:((bearing%360)+360)%360;
 const glyph=window.WindBarb.default(knots,0,{color:'#395766'});
 const children=glyph.children.map(part=>'<'+part.type+' '+Object.entries(part.attr).map(([name,value])=>
  (name==='strokeWidth'?'stroke-width':name)+'="'+escape(name==='strokeWidth'?1.4:value)+'"').join(' ')+'/>').join('');
 const pivot=rounded===0?'9 12.5':'9 25';
 const label=rounded===0?(speed===0?'calm':'&lt;2.5kt'):compass[Math.round(angle/45)%8];
 return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 80">'+
  '<g transform="translate(32 32) rotate('+angle+') translate(-'+pivot.replace(' ',' -')+')" stroke-linecap="round" stroke-linejoin="round">'+children+'</g>'+
  '<text x="32" y="76" text-anchor="middle" font-family="system-ui,sans-serif" font-size="10" fill="#59717e">'+label+'</text></svg>';
}
window.WindBarbs=Object.freeze({svg});
})();
