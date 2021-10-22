import init, { parse, } from "https://deno.land/x/yaml_wasm@0.1.9/index.js";
const { run, readDirSync, readTextFile, writeTextFile } = Deno;

await init();

const errorHandler = async (result: Number, file: any) => {
  if (result !== 0) {
    const rawError = await file.stderrOutput();
    const errorString = new TextDecoder().decode(rawError);
    console.log(`error: ${errorString}`);
    await file.close();
    return Promise.reject(errorString);
  }
  return Promise.resolve();
};

interface ShOpts {
    stdout?: 'inherit' | 'piped' | 'null' | number;
    stderr?: 'inherit' | 'piped' | 'null' | number;
  }
  
const standardCommandArgs: ShOpts = { stdout: 'piped', stderr: 'piped' };

const branchName = "chore/adjust-container-count";
const location = "testutils/infra/container_manager/docker_compose_manager.py";

const maybeCreatePr = async () => {
  let command: Array<string> = ["git", "diff", "--exit-code", location]
  let cmd = run({ ...standardCommandArgs, cmd: command });
  const { code: diffCode } = await cmd.status();
  if (diffCode === 0) {
    cmd.close();
    return Promise.resolve();
  }
  await cmd.close()

  cmd = run({ ...standardCommandArgs, cmd: ["git", "add", "-v", location] });
  const { code: addCode } = await cmd.status();
  await errorHandler(addCode, cmd);
  cmd.close();

  command = [
    "git",
    "commit",
    "-sm",
    "aligned container count with docker compositions\nChangelog: None\n",
  ];
  cmd = run({ ...standardCommandArgs, cmd: command });
  const { code: commitCode } = await cmd.status();
  await errorHandler(commitCode, cmd);
  cmd.close();

  command = ['git', 'push', 'origin', branchName, '--force'];
  cmd = run({ ...standardCommandArgs, cmd: command });
  const { code: pushCode } = await cmd.status();
  await errorHandler(pushCode, cmd);
  cmd.close();

  command = [
    "hub",
    "pull-request",
    "-p",
    "-b",
    "master",
    "-m",
    '"Container count adjustment"',
    "-m",
    '"There seems to be a mismatch in the container count"',
  ];
  cmd = run({ ...standardCommandArgs, cmd: command });
  const { code } = await cmd.status();
  await errorHandler(code, cmd);
  cmd.close();
};

const adjustCountFile = async (osCount: number, enterpriseCount: number) => {
  const configText = await readTextFile(location);
  let lines = configText.split('\n');
  const osLineIndex = lines.findIndex(line => line.includes('NUM_SERVICES_OPENSOURCE'));
  const osLine = lines[osLineIndex];
  lines[osLineIndex] = `${osLine.substring(0, osLine.indexOf('='))}= ${osCount}`;
  const enterpriseLine = lines[osLineIndex + 1];
  lines[osLineIndex + 1] = `${enterpriseLine.substring(0, enterpriseLine.indexOf('='))}= ${enterpriseCount}`;
  return await writeTextFile(location, lines.join('\n'));
};


const createBranch = async () => {
  console.log("setting up new branch");
  const branch = run(
    {
      ...standardCommandArgs,
      cmd: ["git", "checkout", "-B", branchName],
    },
  );
  const { code: branchCode } = await branch.status();
  await errorHandler(branchCode, branch);
  return await branch.close();
};

const processComposition = async (location: string) => {
  const composeFile = await readTextFile(location);
  let [compose] = parse(composeFile);
  return Object.keys(compose.services)
};


const cleanupFilenames = (accu: Array<string>, name: string) => {
  const trimmedName = name.trim();
  if(trimmedName) {
    accu.push(trimmedName)
  }
  return accu;
}

const demoFileLocation = 'demo';
const demoFileList = 'DEMO_FILES="';
const enterpriseFileList = 'ENTERPRISE_FILES="';

const readDemoScript = async () => {
  const demoScript = await readTextFile(demoFileLocation);
  const demoLines = demoScript.split('\n')
  const osLine: string = demoLines.find(line => line.startsWith(demoFileList)) ?? ''
  const relevantOSServices = osLine.substring(demoFileList.length, osLine.length - 1).split('-f').reduce(cleanupFilenames, []);
  const enterpriseLine: string = demoLines.find(line => line.startsWith(enterpriseFileList)) ?? ''
  const relevantEnterpriseServices = enterpriseLine.substring(enterpriseFileList.length, enterpriseLine.length - 1).split('-f').reduce(cleanupFilenames, []);
  return { relevantOSServices, relevantEnterpriseServices };
}

const { relevantOSServices, relevantEnterpriseServices } = await readDemoScript();

let allOSServices = [];
let allEnterpriseServices = [];
for (const thing of readDirSync('.')) {
  const { name } = thing;
  const fileInfo = await Deno.lstat(name);
  if (!fileInfo.isDirectory && relevantOSServices.includes(name)) {
    const services = await processComposition(name);
    allOSServices.push(...services);
  }
  if (!fileInfo.isDirectory && relevantEnterpriseServices.includes(name)) {
    const services = await processComposition(name);
    allEnterpriseServices.push(...services);
  }
}

const osServicesCount = new Set(allOSServices).size;
const enterpriseServicesCount = new Set([...allEnterpriseServices, ...allOSServices]).size;

await createBranch();
await adjustCountFile(osServicesCount, enterpriseServicesCount);
await maybeCreatePr();
