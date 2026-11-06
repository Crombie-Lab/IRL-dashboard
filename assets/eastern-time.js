/* Format local labels without shifting UTC plot coordinates or elapsed durations. */
(function(){
const zone='America/New_York';
const full=new Intl.DateTimeFormat('en-US',{timeZone:zone,month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'});
const day=new Intl.DateTimeFormat('en-US',{timeZone:zone,month:'short',day:'numeric'});
const clock=new Intl.DateTimeFormat('en-US',{timeZone:zone,hour:'numeric',minute:'2-digit',timeZoneName:'short'});
const parts=new Intl.DateTimeFormat('en-US',{timeZone:zone,year:'numeric',month:'numeric',day:'numeric',hour:'numeric',minute:'numeric',hourCycle:'h23'});
const format=value=>value==null?'Not available':full.format(new Date(value));
function ticks(start,end,width){
 const target=(end-start)/Math.max(2,Math.floor(width/120));
 const step=[15,30,60,180,360,720,1440,2880,4320,10080].find(minutes=>minutes*60000>=target)||10080;
 const tickvals=[],ticktext=[];
 function add(time){const date=new Date(time);tickvals.push(date.toISOString());ticktext.push(day.format(date)+'<br>'+clock.format(date));}
 // Select local clock boundaries by inspecting actual instants. DST's repeated
 // hour stays distinct (EDT/EST); a nonexistent spring-forward hour is never made up.
 for(let time=Math.ceil(start/900000)*900000;time<=end;time+=900000){
  const p=Object.fromEntries(parts.formatToParts(new Date(time)).map(p=>[p.type,p.value]));
  const minutes=Number(p.hour)*60+Number(p.minute);
  const localDay=Date.UTC(Number(p.year),Number(p.month)-1,Number(p.day))/86400000;
  if(step<1440?minutes%step===0:minutes===0&&localDay%(step/1440)===0) add(time);
 }
 if(!tickvals.length&&Number.isFinite(start)&&Number.isFinite(end)) add((start+end)/2);
 return {tickmode:'array',tickvals,ticktext};
}
window.EasternTime=Object.freeze({format,ticks});
})();
