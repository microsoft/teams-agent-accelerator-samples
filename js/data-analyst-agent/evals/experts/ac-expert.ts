import { ConsoleLogger } from '@teams.sdk/common';
import { AdaptiveCardExpert } from '../../src/agents/ac-expert';
import { ACJudge } from '../judge/ac';
import * as fs from 'fs';
import * as path from 'path';

interface EvalCase {
    task: string;
    input_data: Array<object>;
    visualization_type: string;
    expected_card: object;
}

interface EvalResult {
    task: string;
    input_data: string;
    visualization_type: string;
    expected_card: string;
    actual_card?: string;
    success: boolean;
    judge_result: {
        choice: 'Correct' | 'Incorrect';
        score: number;
        reason?: string;
    };
    error?: string;
}

async function evaluateACExpert() {
    const log = new ConsoleLogger('ac-expert-eval', { level: 'debug' });
    const judge = ACJudge();

    // Load test cases
    const evalFilePath = path.join(__dirname, '..', 'ac-eval.jsonl');
    const evalContent = fs.readFileSync(evalFilePath, 'utf-8');
    const evalCases: EvalCase[] = JSON.parse(evalContent);

    // Check if run-one flag is passed
    const runOne = process.argv.includes('--run-one');
    const casesToRun = runOne ? evalCases.slice(1, 2) : evalCases;
    const results: EvalResult[] = [];

    // Run each test case
    for (const testCase of casesToRun) {
        log.info(`Evaluating: ${testCase.task}`);
        
        try {
            const expert = AdaptiveCardExpert();
            const response = await expert.chat(
                `Create a ${testCase.visualization_type} visualization for this data: ${JSON.stringify(testCase.input_data)}`
            );
            const parsedResponse = JSON.parse(response);

            // Get judgment from AC judge
            const judgeResult = await judge.evaluate({
                input: JSON.stringify(testCase.input_data),
                ideal: JSON.stringify(testCase.expected_card),
                completion: JSON.stringify(parsedResponse)
            });

            results.push({
                task: testCase.task,
                input_data: JSON.stringify(testCase.input_data, null, 2),
                visualization_type: testCase.visualization_type,
                expected_card: JSON.stringify(testCase.expected_card, null, 2),
                actual_card: JSON.stringify(parsedResponse, null, 2),
                success: judgeResult.choice === 'Correct',
                judge_result: {
                    choice: judgeResult.choice,
                    score: judgeResult.score,
                    reason: judgeResult.reason
                }
            });
        } catch (error) {
            results.push({
                task: testCase.task,
                input_data: JSON.stringify(testCase.input_data, null, 2),
                visualization_type: testCase.visualization_type,
                expected_card: JSON.stringify(testCase.expected_card, null, 2),
                success: false,
                judge_result: {
                    choice: 'Incorrect',
                    score: 0,
                    reason: error instanceof Error ? error.message : 'Unknown error'
                },
                error: error instanceof Error ? error.message : 'Unknown error',
            });
        }
    }

    // Output results
    outputResults(results);
}

function outputResults(results: EvalResult[]) {
    const totalTests = results.length;
    const successfulTests = results.filter(r => r.success).length;
    const failedTests = totalTests - successfulTests;

    const timestamp = new Date().toISOString().replace(/:/g, '-');
    const logFile = path.join(__dirname, `ac-expert-eval-${timestamp}.log`);
    let output = '';

    output += '\n=== Adaptive Card Expert Evaluation Results ===\n\n';
    output += `Total Tests: ${totalTests}\n`;
    output += `Successful: ${successfulTests}\n`;
    output += `Failed: ${failedTests}\n`;
    output += `Success Rate: ${((successfulTests / totalTests) * 100).toFixed(2)}%\n\n`;

    // Output detailed results
    results.forEach((result, index) => {
        output += `\n--- Test Case ${index + 1}: ${result.task} ---\n`;
        output += `Success: ${result.success ? '✅' : '❌'}\n`;
        output += `Visualization Type: ${result.visualization_type}\n`;
        output += `Input Data: ${result.input_data}\n`;
        output += `\nActual Card Output:\n${result.actual_card}\n`;
        output += `Judge Result: ${result.judge_result.choice} (Score: ${result.judge_result.score})\n`;
        if (result.judge_result.reason) {
            output += `Judge Reasoning: ${result.judge_result.reason}\n`;
        }
        
        if (!result.success && result.error) {
            output += `\nError: ${result.error}\n`;
        }
    });

    // Write to file and console
    fs.writeFileSync(logFile, output);
    console.log(`\nResults written to: ${logFile}`);
}

// Run evaluation
evaluateACExpert().catch(error => {
    console.error('Evaluation failed:', error);
    process.exit(1);
}); 