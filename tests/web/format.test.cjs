const {test} = require('node:test');
const assert = require('node:assert/strict');
const format = require('../../src/footy/web/static/format.js');

test('montos CLP con miles de Chile, signo y ausencia de datos', () => {
  assert.equal(format.money(100000),'$100.000');
  assert.equal(format.money(-5000),'$-5.000');
  assert.equal(format.money(0),'$0');
  assert.equal(format.money(null),'–');
  assert.equal(format.money(NaN),'–');
});

test('el monto formateado vuelve al mismo número sin multiplicar los miles', () => {
  for (const n of [100000, 5000, 1000.5, 1.123, 0, -5000]) {
    assert.equal(format.parseAmount(format.amount(n)),n);
    assert.equal(format.parseAmount(n),n);
  }
  assert.equal(format.parseAmount('$100.000'),100000);
  assert.equal(format.parseAmount('100000'),100000);
  assert.equal(format.parseAmount('1000,5'),1000.5);
  for (const value of ['', 'abc', '1.2.3', '1e3', Infinity, '9'.repeat(400)]) assert.ok(Number.isNaN(format.parseAmount(value)));
});
