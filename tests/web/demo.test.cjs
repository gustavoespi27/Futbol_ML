const {test}=require('node:test');
const assert=require('node:assert/strict');
const demo=require('../../src/footy/web/static/demo.js');
test('presentación apagada por defecto, consulta y sesión explícitas',()=>{
 assert.equal(demo.enabled('',null),false);assert.equal(demo.enabled('?demo',null),true);
 assert.equal(demo.enabled('','1'),true);assert.equal(demo.enabled('?demo=0','1'),false);
});
test('herramientas se agrupan sin cambiar el orden de observaciones',()=>{
 let rows=demo.append([],'step',{kind:'observation',text:'Sin Pinnacle'});
 rows=demo.append(rows,'tool_start',{tool:'request_odds'});
 rows=demo.append(rows,'step',{kind:'deviation',text:'Otra vía'});
 const previous=rows;
 rows=demo.append(rows,'tool_result',{tool:'request_odds',success:true,elapsed_ms:12.3,summary:'Tres precios'});
 assert.equal(rows.length,3);assert.equal(rows[1].label,'Consultó al Ojeador');
 assert.equal(rows[1].success,true);assert.equal(rows[1].ms,12.3);assert.equal(rows[2].text,'Otra vía');
 assert.equal(previous[1].pending,true);
});
test('llamadas repetidas y fallos no se pierden',()=>{
 let rows=demo.append([],'tool_start',{tool:'find_team'});
 rows=demo.append(rows,'tool_result',{tool:'find_team',success:false,elapsed_ms:NaN});
 rows=demo.append(rows,'tool_start',{tool:'find_team'});
 rows=demo.append(rows,'tool_result',{tool:'find_team',success:true,elapsed_ms:1});
 assert.equal(rows.length,2);assert.equal(rows[0].success,false);assert.equal(rows[0].ms,null);
 assert.equal(rows[1].success,true);
 assert.equal(demo.append([],'tool_result',{tool:'unknown'}).length,1);
 assert.deepEqual(demo.append(rows,'token',{delta:'texto'}),rows);
});
