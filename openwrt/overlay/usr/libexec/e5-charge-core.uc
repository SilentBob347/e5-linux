// Existing charger-manager/AW322xx policy, with native file/UCI operations.
// Does not change JEITA, voltage/current limits, low-battery or thermal policy.
import * as fs from 'fs';
import { cursor } from 'uci';
export function controller(root,config) {
    root ??= '';config ??= '/etc/config';
    const bat=root+'/sys/class/power_supply/battery', ctl=bat+'/charger.0/stop_charge';
    const hiz=root+'/sys/class/power_supply/aw322xx_charger/high_impedance_enable';
    const state=root+'/tmp/run/e5-charge';
    function rd(path) {return trim(fs.readfile(path) || '');}
    function put(path,value) {if(fs.writefile(path,''+value+'\n')==null)die('e5-charge: control write failed\n');}
    function cfg(c,key,d) {return c.get('e5-charge','main',key) ?? d;}
    function settings() {
        let c=cursor(config), enabled=cfg(c,'enabled','0'), full=cfg(c,'full_once','0');
        let start=cfg(c,'start','70'), stop=cfg(c,'stop','80');
        if(!(enabled in ['0','1']) || !(full in ['0','1']) ||
           !match(start,/^[0-9]{1,3}$/) || !match(stop,/^[0-9]{1,3}$/) ||
           +start>100 || +stop>100 || +stop<1)die('e5-charge: invalid saved limits\n');
        // Preserve the historical gap repair for an old manually written config.
        start=+start;stop=+stop;if(start>=stop)start=stop-5;
        return {c,enabled:enabled=='1',full:full=='1',start,stop};
    }
    function online() {
        return rd(root+'/sys/class/power_supply/usb/online')=='1' ||
               rd(root+'/sys/class/power_supply/ac/online')=='1';
    }
    let stopped=0;
    function set_stop(value) {
        if(!fs.access(ctl,'w'))return false;
        if(value) {
            put(ctl,1);
            if(fs.access(hiz,'w'))put(hiz,1);
        } else {
            // Attempt both release writes even when one driver rejects its
            // control. A failed HiZ release must not skip manager resume.
            let failed=fs.access(hiz,'w') && fs.writefile(hiz,'0\n')==null;
            if(fs.writefile(ctl,'0\n')==null)failed=true;
            if(failed)die('e5-charge: unable to release all charging controls\n');
        }
        put(state+'/stopped',value);return true;
    }
    function tick() {
        let s=settings(), raw=rd(bat+'/capacity');
        if(!match(raw,/^[0-9]{1,3}$/) || +raw>100)die('e5-charge: battery capacity unavailable\n');
        let cap=+raw, want=stopped;
        if(s.full) {
            want=0;
            if(cap>=100 || rd(bat+'/status')=='Full') {
                if(!s.c.set('e5-charge','main','full_once','0') || !s.c.commit('e5-charge'))
                    die('e5-charge: cannot clear full-once setting\n');
            }
        } else if(!s.enabled)want=0;
        else if(cap>=s.stop)want=1;
        else if(cap<=s.start)want=0;
        if(online()) {
            if(want!=stopped || !fs.stat(state+'/stopped') ||
               (want==1 && fs.access(hiz,'w') && rd(hiz)!='1')) {
                if(set_stop(want))stopped=want;
            }
        } else if(stopped==1) {stopped=0;fs.unlink(state+'/stopped');}
    }
    function status() {
        let s=settings();
        return sprintf('capacity=%s status=%s stopped=%s enabled=%d stop=%d start=%d full_once=%d\n',
            rd(bat+'/capacity'),rd(bat+'/status'),rd(state+'/stopped') || '0',s.enabled?1:0,s.stop,s.start,s.full?1:0);
    }
    function init() {
        fs.mkdir(root+'/tmp/run');fs.mkdir(state);
        // An earlier owner must never leave this no-power-path board in HiZ.
        if(fs.access(hiz,'w'))put(hiz,0);
        fs.unlink(state+'/stopped');stopped=0;
    }
    return {tick,status,init,stop:()=>set_stop(0)};
};
