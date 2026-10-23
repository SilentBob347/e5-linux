"""Exercise the production C request/UTF-8 parsers under ASan and UBSan."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class Sanitizer(unittest.TestCase):
    def test_malformed_bounded_packets_do_not_read_outside_input(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'fuzz.c'
            source.write_text('#define main owner_main\n#include '+json.dumps(str(Path(__file__).with_name('atd.c')))+'\n#undef main\n'+r'''
int main(void) {
    unsigned seed=42;
    char packet[4097];struct request r;
    const char *bad[]={"", "{", "{\"", "{\"command\":\"AT\\u", "{\"x\":[[[", "{\"x\":-", "{\"x\":1e", "{\"x\":true,", "{\"command\":\"AT\\"};
    for(size_t i=0;i<sizeof(bad)/sizeof(bad[0]);i++)parse(bad[i],&r);
    for(int round=0;round<20000;round++) {
        seed=seed*1664525u+1013904223u;size_t size=seed%4096;
        for(size_t n=0;n<size;n++){seed=seed*1664525u+1013904223u;packet[n]=(char)(1+(seed%255));}
        packet[size]=0;
        if(size>0 && round%2)packet[0]='{';
        parse(packet,&r);
        char *out=NULL;size_t length=0;FILE *f=open_memstream(&out,&length);
        if(!f)return 1;
        quoted(f,packet);fclose(f);free(out);
    }
    snprintf(packet,sizeof(packet),"{\"command\":\"AT+CSQ\",\"deadline\":%.6f,\"unknown\":{\"nested\":[true,null,1e2]}}",now()+10);
    if(parse(packet,&r)||strcmp(r.command,"AT+CSQ"))return 2;
    puts("PASS: 20000 bounded malformed JSON/UTF-8 packets, ASan/UBSan clean");return 0;
}
''')
            binary=root/'fuzz'
            subprocess.run(['cc','-std=c11','-O1','-g','-fno-omit-frame-pointer','-fsanitize=address,undefined',
                            '-fno-pie','-no-pie',str(source),'-o',str(binary)],check=True)
            p=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30,
                             env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1'))
            self.assertEqual(p.returncode,0,p.stderr);print(p.stdout.strip())


if __name__=='__main__':unittest.main()
