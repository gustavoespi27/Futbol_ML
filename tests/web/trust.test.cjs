const {test} = require('node:test');
const assert = require('node:assert/strict');
const trust = require('../../src/footy/web/static/trust.js');

const now = Date.parse('2026-11-09T15:00:00Z');
test('la frontera exacta de treinta horas ya pausa recomendaciones', () => {
  assert.equal(trust.classify({last_daily_run:new Date(now-30*3600000+1).toISOString()},now),'fresh');
  assert.equal(trust.classify({last_daily_run:new Date(now-30*3600000).toISOString()},now),'stale');
});
test('fecha ausente, inválida o futura no permite afirmar datos al día', () => {
  for (const value of [null, {}, {last_daily_run:'error'}, {last_daily_run:new Date(now+3600000).toISOString()}]) {
    assert.equal(trust.classify(value,now),'unknown');
  }
});
test('los fallos y la falta de datos prevalecen sobre listas vacías', () => {
  for (const state of ['error','unknown','stale']) assert.equal(trust.emptyKind(state,0,0),state);
  assert.equal(trust.emptyKind('fresh',0,0),'no_matches');
  assert.equal(trust.emptyKind('fresh',5,0,0),'no_reference');
  assert.equal(trust.emptyKind('fresh',5,0,3),'no_value');
  assert.equal(trust.emptyKind('fresh',5,1,3),null);
});
test('una plantilla con partidos no se etiqueta como nada destacado', () => {
  assert.equal(trust.briefingLabel({iterations:0,success:true}),'Resumen automático (sin IA)');
  assert.match(trust.briefingLabel({iterations:1,success:true}),/Redactado por el asistente/);
  assert.match(trust.briefingLabel({iterations:1,success:false}),/No se completó/);
});

test('cobertura del calendario: nula, parcial y completa', () => {
  for (const n of [0, 1, 40]) {
    const matches = Array.from({length:40}, (_,i)=>({kickoff:new Date(now+3600000).toISOString(),pro:i<n?[{}]:[]}));
    assert.deepEqual(trust.coverage(matches),{reference:n,total:40,missing:40-n,label:`${n} de 40 con Pinnacle`});
  }
  assert.equal(trust.partidos(1),'1 partido');
  assert.equal(trust.partidos(40),'40 partidos');
});

test('fecha relativa según el día de Chile, incluso al cruzar medianoche UTC', () => {
  const clock = Date.parse('2026-11-10T02:30:00Z'); // 9 de noviembre, 23:30 en Chile
  assert.equal(trust.updatedTime('2026-11-10T01:00:00Z',clock),'hoy a las 22:00');
  assert.equal(trust.updatedTime('2026-11-09T02:00:00Z',clock),'ayer a las 23:00');
  assert.match(trust.updatedTime('2026-11-07T15:00:00Z',clock),/^el 7 de noviembre de 2026$/);
});
