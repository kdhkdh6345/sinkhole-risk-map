import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { Simulator } from '../web/js/sim.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const configPath = path.join(__dirname, '../web/data/config.json');
const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));

const parityPath = path.join(__dirname, 'fixtures/parity.json');
const parityData = JSON.parse(fs.readFileSync(parityPath, 'utf8'));

const sim = new Simulator(config);

let passed = 0;
let failed = 0;

for (const item of parityData) {
    const input = item.input;
    const expected = item.expected;
    
    // JS 엔진에 맞게 cell 객체 구성
    // getScenarioRawValues를 우회하여 원시값을 주입하기 위해 임시로 오버라이드
    const cell = {
        id: item.id,
        b: input.b,
        gu: "test" // 시나리오 원시값 대신 input의 값을 쓰도록
    };

    // JS Simulator는 원본적으로 getScenarioRawValues를 통해 rain, sigma, deg를 가져옴.
    // Parity 테스트를 위해 시뮬레이터 인스턴스의 getScenarioRawValues를 모의(Mock) 처리.
    sim.getScenarioRawValues = () => ({
        rainArr: [input.r1, input.r3, input.r12],
        sigma: input.sigma,
        deg: input.deg
    });

    const result = sim.simulateCell(cell, input.elapsed_h, "custom");
    
    // 오차 허용 범위
    const EPSILON = 0.01;
    
    let isOk = true;
    const check = (key, val, exp) => {
        if (Math.abs(val - exp) >= EPSILON) {
            console.error(`[FAIL] ${item.desc} - ${key} mismatch: got ${val}, expected ${exp}`);
            isOk = false;
        }
    };

    check("r", result.r, expected.r);
    check("g", result.g, expected.g);
    check("t", result.t, expected.t);
    check("score", result.score, expected.score);
    
    if (result.stage !== expected.stage) {
        console.error(`[FAIL] ${item.desc} - stage mismatch: got ${result.stage}, expected ${expected.stage}`);
        isOk = false;
    }

    if (isOk) {
        console.log(`[OK] ${item.desc}`);
        passed++;
    } else {
        failed++;
    }
}

console.log(`\nParity Test Results: ${passed} passed, ${failed} failed`);
if (failed > 0) {
    process.exit(1);
} else {
    process.exit(0);
}
