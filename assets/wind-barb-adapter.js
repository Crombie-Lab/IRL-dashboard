/* Display Matplotlib-generated SVG paths; speeds enter in m/s, bearings are FROM north. */
(function(){
const compass=['N','NE','E','SE','S','SW','W','NW'];
function svg(speed,bearing){
 if(!Number.isFinite(speed)||speed<0) return null;
 const glyphs=window.MatplotlibBarbPaths;
 const knots=speed/0.5144444444444445;
 const index=Math.round(knots/glyphs.step_knots);
 if(index>=glyphs.paths.length||(index>0&&!Number.isFinite(bearing))) return null;
 const angle=index===0?0:((bearing%360)+360)%360;
 const mph=(speed/0.44704).toFixed(1);
 const label=index===0?(speed===0?'calm':mph+' mph'):compass[Math.round(angle/45)%8];
 const description=mph+' mph'+(Number.isFinite(bearing)?' from '+compass[Math.round(angle/45)%8]:'');
 return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 80" role="img">'+
  '<title>'+description+'</title><g transform="translate(32 30) rotate('+angle+') scale('+glyphs.scales[index]+')">'+
  '<path d="'+glyphs.paths[index]+'" fill="'+(index===0?'none':'#28485a')+'" stroke="#28485a" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></g>'+
  '<text x="32" y="76" text-anchor="middle" font-family="system-ui,sans-serif" font-size="10" fill="#59717e">'+label+'</text></svg>';
}
window.WindBarbs=Object.freeze({svg});
})();
