// Read-only methods; no caller-supplied commands, interface names or paths.
import * as dash from 'e5.dash';
return {e5status:{
    status:{args:{slot:''},call:req=>dash.status(req.args.slot,false)},
    cells:{args:{slot:''},call:req=>dash.status(req.args.slot,true)},
    rates:{args:{slot:''},call:req=>dash.rates(req.args.slot)},
    sysinfo:{args:{slot:''},call:req=>dash.info(req.args.slot || null)},
    sms_head:{call:()=>dash.sms_head()}
}};
