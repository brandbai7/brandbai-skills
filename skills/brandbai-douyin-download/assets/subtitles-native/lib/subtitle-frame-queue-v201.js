/* Bounded scan scheduling only: no pixels, recognition or source authority.
 * A caller checkpoint must enforce its pause/cancel/source lease before every
 * prepare and commit. The caller owns workers and terminates all of them in
 * cleanup, including a worker whose outstanding run has not yet settled.
 */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;root.BrandbaiSubtitleFrameQueueV201=api;})(globalThis,function(){
  'use strict';
  // Resolve once at task creation. Hardware hints are not a speed guarantee.
  // Keep the serial baseline until repeatable benefits are validated. Two
  // workers remain an explicit internal experiment, not a user-facing default.
  function selectFrameConcurrency(budget={}){
    const cpu=Number.isSafeInteger(budget.hardwareConcurrency)&&budget.hardwareConcurrency>0?budget.hardwareConcurrency:null;
    const memory=Number.isFinite(budget.deviceMemory)&&budget.deviceMemory>0?budget.deviceMemory:null;
    const requested=[1,2].includes(budget.requested)?budget.requested:'auto';
    const resume=budget.resume===true;
    const capacity=resume?1:requested!=='auto'?requested:1;
    const reason=resume?'precision_resume_no_scan':requested!=='auto'?'explicit_internal_override':'serial_baseline_parallel_benefit_not_established';
    return Object.freeze({schema:'subtitle-scan-budget-v201',requested,capacity,reason,hardwareConcurrency:cpu,deviceMemoryGiB:memory,memoryHint:'coarse_total_not_available_memory',scanApplicable:!resume});
  }
  async function runOrderedFrames(options){
    const {count,prepare,run,commit,cleanup,signal}=options||{};
    const checkpoint=options?.checkpoint||(()=>{}),capacity=options?.capacity??2;
    if(!Number.isSafeInteger(count)||count<0||![1,2].includes(capacity))throw TypeError('Invalid bounded frame queue size');
    for(const fn of [prepare,run,commit,checkpoint,cleanup])if(typeof fn!=='function')throw TypeError('Frame queue callbacks are required');
    let failure=null,next=0,head=0,peak=0,wake=null,stopResolve;
    const tasks=new Map(),free=Array.from({length:capacity},(_,i)=>i);
    // This promise resolves, never rejects: racing checkpoints cannot create
    // an unhandled rejection after an unrelated run has already failed.
    const stopped=new Promise(resolve=>{stopResolve=resolve;});
    const notify=()=>{if(wake){const resolve=wake;wake=null;resolve();}};
    const fail=error=>{if(!failure){failure=error instanceof Error?error:Error(String(error||'Frame queue stopped'));stopResolve();notify();}};
    const abort=()=>fail(signal?.reason instanceof Error?signal.reason:Object.assign(Error('Frame queue cancelled'),{name:'AbortError'}));
    const check=()=>{if(signal?.aborted)abort();if(failure)throw failure;};
    // Pause can block here. A different task's error or signal cancels the
    // scheduler even when that pause promise is still unresolved. Its eventual
    // rejection is handled by Promise.race; no preparation/commit follows it.
    const gate=async(phase,index)=>{check();await Promise.race([Promise.resolve().then(()=>checkpoint({phase,index,signal})),stopped]);check();};
    if(signal)signal.addEventListener('abort',abort,{once:true});
    let outcome;
    try{
      check();
      while(head<count){
        while(next<count&&tasks.size<capacity){
          await gate('before_prepare',next);
          const index=next++,slot=free.shift(),task={index,slot,payload:null,result:null,done:false};
          tasks.set(index,task);peak=Math.max(peak,tasks.size);
          // Never race or parallelize this callback: a source player seek may
          // still be in progress when cancellation arrives. Let it settle,
          // then reject before starting inference or another seek.
          task.payload=await prepare(index,slot);
          check();
          task.pending=Promise.resolve().then(()=>{check();return run(task.payload,slot,index);}).then(
            result=>{task.result=result;task.done=true;notify();},
            error=>{task.done=true;fail(error);}
          );
        }
        check();
        const task=tasks.get(head);
        if(!task?.done){await new Promise(resolve=>{wake=resolve;});continue;}
        await gate('before_commit',head);
        await commit(task.payload,task.result,head,task.slot);
        check();
        task.payload=null;task.result=null;tasks.delete(head);free.push(task.slot);head++;
      }
      outcome={committed:head,prepared:next,peakInFlight:peak,capacity};
    }catch(error){fail(error);}
    finally{
      if(signal)signal.removeEventListener('abort',abort);
      // All run promises already have rejection handlers. Cleanup terminates
      // owned workers rather than waiting indefinitely on an inference hang.
      try{await cleanup({error:failure,committed:head,prepared:next});}
      catch(error){fail(error);}
      tasks.clear();
    }
    if(failure)throw failure;
    return outcome;
  }
  return Object.freeze({runOrderedFrames,selectFrameConcurrency});
});
