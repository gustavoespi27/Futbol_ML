const { test } = require('node:test');
const assert = require('node:assert/strict');
const names = require('../../src/footy/web/static/team-display.json');
const { translator } = require('../../src/footy/web/static/team-display.js');

test('traduce nombres públicos completos y juveniles sin alterar números ni cadenas parciales', () => {
  const display = translator(names);
  assert.equal(display('Czechia vs Spain 90.7% · Chinese Taipei a 1.30'),
    'Chequia vs España 90.7% · Taiwán a 1.30');
  assert.equal(display('Spain U21 vs Spainville'), 'España U21 vs Spainville');
  assert.equal(display('Colo-Colo vs la U'), 'Colo-Colo vs la U');
});
