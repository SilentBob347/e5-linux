// Native USB watchdog. Same SDP/CDP, extcon, lock and five-attempt policy.
// No gadget unbind, netdev down, routing changes or alternate backend.
import * as fs from 'fs';
export function watchdog(root) {
    root ??= '';
    let missed=0,attempts=0,next=0,cooldown=0,disconnected=false,udc=null;
    function rd(p) {return trim(fs.readfile(root+p) || '');}
    function exists(p) {return fs.stat(root+p)!=null;}
    function now() {return +split(rd('/proc/uptime'),' ')[0];}
    function put(value) {
        if(fs.writefile(root+udc+'/soft_connect',value+'\n')==null)
            die('e5-usb-watch: soft_connect failed\n');
    }
    function vbus() {
        for(let path in fs.glob(root+'/sys/class/extcon/*/state') || [])
            if(index(split(trim(fs.readfile(path) || ''),'\n'),'USB=1')>=0)return true;
        return false;
    }
    function host() {
        for(let path in fs.glob(root+'/sys/class/power_supply/*/usb_type') || []) {
            let base=replace(path,/\/usb_type$/,'');
            if(trim(fs.readfile(base+'/online') || '')=='1' &&
               match(trim(fs.readfile(path) || ''),/\[(SDP|CDP)\]/))return true;
        }
        return false;
    }
    const started=now();
    function tick() {
        const stamp=now();
        if(!udc || !exists(udc)) {
            udc=null;
            for(let path in fs.glob(root+'/sys/class/udc/*') || []) {udc=substr(path,length(root));break;}
            if(!udc) {
                if(stamp-started>=60)die('e5-usb-watch: no USB device controller after 60 seconds\n');
                return 1000;
            }
        }
        if(exists('/tmp/run/e5-usb-reset/lock')) {
            missed=0;attempts=0;disconnected=false;next=stamp+2;return 2000;
        }
        if(disconnected) {
            if(stamp<cooldown)return max(1,int((cooldown-stamp)*1000));
            put('connect');disconnected=false;cooldown=stamp+10;next=stamp+2;return 2000;
        }
        if(!vbus() || !host()) {missed=0;attempts=0;next=stamp+2;return 2000;}
        let state=rd(udc+'/state');
        if(state=='configured') {missed=0;attempts=0;next=stamp+2;return 2000;}
        if(stamp<next || stamp<cooldown)return 2000;
        next=stamp+2;missed++;
        if(missed>=3 && attempts<5) {
            missed=0;attempts++;
            if(state=='not attached') {put('connect');cooldown=stamp+10;}
            else {put('disconnect');disconnected=true;cooldown=stamp+1;return 1000;}
        }
        return 2000;
    }
    function stop() {
        if(disconnected && !exists('/tmp/run/e5-usb-reset/lock'))put('connect');
        disconnected=false;
    }
    return {tick,stop};
};
